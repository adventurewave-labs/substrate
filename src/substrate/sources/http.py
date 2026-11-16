"""Polite HTTP: one chokepoint for every outbound fetch.

Rate-limited per host, robots.txt honored (cached, RFC-7694 404→allow convention),
bounded retries with backoff, and an injectable transport so tests never touch the
network. Unstructured crawl data is untrusted input — responses stay bytes+headers,
parsing happens in typed parsers downstream.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlparse

DEFAULT_USER_AGENT = (
    "substrate-crawler/0.1 (+https://github.com/adventurewave-labs/substrate; "
    "contact: ops@adventurewave-labs.dev)"
)
_MAX_ATTEMPTS = 3
_MAX_REDIRECT_HOPS = 5
_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_MIN_HOST_INTERVAL = 1.0  # seconds between requests to the same host


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> object:
        return json.loads(self.body)

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Transport = Callable[[urllib.request.Request], FetchResponse]


def _disallow_all() -> robotparser.RobotFileParser:
    """Synthetic robots policy: refuse every path (RFC 9309 §2.3.1.4)."""
    parser = robotparser.RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are handled by Fetcher — every hop passes a robots check first."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None  # suppress urllib's automatic redirect


_OPENER = urllib.request.build_opener(_NoRedirect())

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _stdlib_transport(request: urllib.request.Request) -> FetchResponse:
    try:
        with _OPENER.open(request, timeout=30) as resp:  # noqa: S310 — fixed schemes
            return FetchResponse(
                url=resp.geturl(),
                status=resp.status,
                body=resp.read(),
                headers={k.lower(): v for k, v in resp.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        return FetchResponse(
            url=exc.geturl() or request.full_url,
            status=exc.code,
            body=exc.read(),
            headers={k.lower(): v for k, v in exc.headers.items()},
        )


class Fetcher:
    """Polite fetcher. All source modules fetch through this — no direct urllib."""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: Transport | None = None,
        min_host_interval: float = _MIN_HOST_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._ua = user_agent
        self._transport = transport or _stdlib_transport
        self._min_interval = min_host_interval
        self._clock = clock
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.skipped_robots = 0

    # -- robots ---------------------------------------------------------------

    def _robots_for(self, scheme_host: str) -> robotparser.RobotFileParser | None:
        """None = no robots file exists (404) → unrestricted per RFC 9309 §2.3.1.4.
        Unreachable or 4xx/5xx robots.txt → DISALLOW ALL (same RFC section) —
        returned as a synthetic parser that refuses every path."""
        if scheme_host in self._robots:
            return self._robots[scheme_host]
        url = f"https://{scheme_host}/robots.txt"
        resp = None
        exhausted_redirects = False
        try:
            # Follow bounded robots redirects: the destination file IS the policy.
            # Exhausting the budget leaves the request UNRESOLVED — that is
            # treated as unavailable (disallow-all), never as unrestricted.
            for _hop in range(3):
                resp = self._transport(
                    urllib.request.Request(url, headers={"User-Agent": self._ua})
                )
                if resp.status in _REDIRECT_STATUSES and resp.headers.get("location"):
                    if _hop == 2:
                        exhausted_redirects = True
                        resp = None
                        break
                    url = urljoin(resp.url or url, resp.headers["location"])
                    continue
                break
        except Exception:  # noqa: BLE001 — robots fetch must never break a crawl
            resp = None
        if exhausted_redirects:
            self._robots[scheme_host] = _disallow_all()
            return self._robots[scheme_host]

        parser: robotparser.RobotFileParser | None
        if resp is None or resp.status >= 500 or (400 <= resp.status < 500 and resp.status != 404):
            # RFC 9309 §2.3.1.4: 5xx/unreachable → disallow all. For other 4xx the
            # RFC permits fetching; we choose fail-closed anyway (stricter, safer).
            parser = _disallow_all()
        elif resp.status == 404:
            parser = None  # the site declares no robots file → unrestricted
        else:
            parser = robotparser.RobotFileParser()
            parser.parse(resp.text().splitlines())
        self._robots[scheme_host] = parser
        return parser

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if not host:
            return False
        parser = self._robots_for(host)
        if parser is None:
            return True
        if not parser.can_fetch(self._ua, url):
            self.skipped_robots += 1
            return False
        return True

    # -- fetch ----------------------------------------------------------------

    _ALLOWED_SCHEMES = ("http", "https")

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> FetchResponse:
        scheme = urlparse(url).scheme.lower()
        if scheme not in self._ALLOWED_SCHEMES:
            raise FetchFailed(url, _ServerStatus(f"scheme {scheme!r} not allowed"))
        if not self.allowed(url):
            raise RobotsDisallowed(url)

        host = urlparse(url).netloc
        last_error: Exception | None = None
        hops = 0
        attempts = 0
        while True:
            # Throttle EVERY transport request — including redirect hops on the
            # same host (round-5 gate review).
            now = self._clock()
            since = now - self._last_hit.get(host, 0.0)
            if since < self._min_interval:
                self._sleep(self._min_interval - since)
            self._last_hit[host] = self._clock()
            try:
                resp = self._transport(
                    urllib.request.Request(
                        url, headers={"User-Agent": self._ua, **(headers or {})}
                    )
                )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
            else:
                if resp.status in _REDIRECT_STATUSES:
                    location = resp.headers.get("location")
                    if location:
                        hops += 1
                        if hops > _MAX_REDIRECT_HOPS:
                            raise FetchFailed(url, _ServerStatus("too many redirects"))
                        # Redirects are progress, not failures: they do not consume
                        # the retry budget (round-4 gate review).
                        next_url = urljoin(resp.url or url, location)
                        next_scheme = urlparse(next_url).scheme.lower()
                        if next_scheme not in self._ALLOWED_SCHEMES:
                            raise FetchFailed(
                                next_url,
                                _ServerStatus(f"redirect scheme {next_scheme!r} not allowed"),
                            )
                        if not self.allowed(next_url):
                            raise RobotsDisallowed(next_url)
                        url = next_url
                        host = urlparse(url).netloc
                        continue
                if resp.status < 500:
                    return resp  # 4xx are answers, not failures — callers decide
                last_error = _ServerStatus(f"HTTP {resp.status} for {url}")
            attempts += 1
            if attempts >= _MAX_ATTEMPTS:
                raise FetchFailed(url, last_error)
            self._sleep(_BACKOFF_SECONDS[min(attempts - 1, len(_BACKOFF_SECONDS) - 1)])


class RobotsDisallowed(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(f"robots.txt disallows: {url}")


class FetchFailed(Exception):
    def __init__(self, url: str, cause: Exception | None) -> None:
        super().__init__(f"fetch failed after retries: {url} ({cause})")
        self.cause = cause


class _ServerStatus(Exception):
    pass
