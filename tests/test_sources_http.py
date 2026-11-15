"""Polite HTTP layer — fake transport, never the network."""

import urllib.request

import pytest

from substrate.sources.http import Fetcher, FetchFailed, RobotsDisallowed


def _resp(
    status: int,
    body: bytes = b"{}",
    headers: dict[str, str] | None = None,
    url: str = "https://x.example/",
):
    from substrate.sources.http import FetchResponse

    return FetchResponse(url=url, status=status, body=body, headers=headers or {})


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _transport_serving(responses: dict[str, object]):
    def transport(request: urllib.request.Request):
        url = request.full_url
        item = responses.get(url)
        if item is None:
            raise AssertionError(f"unexpected fetch: {url}")
        if isinstance(item, Exception):
            raise item
        return item

    return transport


def test_robots_disallow_is_honored():
    robots_body = b"User-agent: *\nDisallow: /private/\n"
    fetcher = Fetcher(
        transport=_transport_serving(
            {"https://host.example/robots.txt": _resp(200, robots_body, url="https://host.example/robots.txt")}
        )
    )
    assert fetcher.allowed("https://host.example/public/page") is True
    assert fetcher.allowed("https://host.example/private/secret") is False
    assert fetcher.skipped_robots == 1
    with pytest.raises(RobotsDisallowed):
        fetcher.fetch("https://host.example/private/secret")


def test_robots_404_means_unrestricted():
    fetcher = Fetcher(transport=_transport_serving({"https://host.example/robots.txt": _resp(404)}))
    assert fetcher.allowed("https://host.example/anything") is True


def test_robots_unreachable_means_disallowed():
    # RFC 9309 §2.3.1.4: unavailable robots.txt → disallow ALL. The crawl "does not
    # break" — it returns False, raises nothing.
    fetcher = Fetcher(
        transport=_transport_serving(
            {"https://host.example/robots.txt": TimeoutError("no answer")}
        )
    )
    assert fetcher.allowed("https://host.example/anything") is False
    assert fetcher.skipped_robots == 1


def test_robots_5xx_means_disallowed():
    fetcher = Fetcher(
        transport=_transport_serving({"https://host.example/robots.txt": _resp(503)})
    )
    assert fetcher.allowed("https://host.example/anything") is False


def test_server_errors_retry_then_succeed():
    clock = FakeClock()
    robots = {"https://host.example/robots.txt": _resp(404)}
    calls = {"n": 0}

    def transport(request: urllib.request.Request):
        if request.full_url.endswith("/flaky"):
            calls["n"] += 1
            if calls["n"] < 3:
                return _resp(503)
            return _resp(200, b'{"ok": true}')
        return robots.get(request.full_url, _resp(404))

    fetcher = Fetcher(transport=transport, clock=clock, sleep=clock.sleep)
    resp = fetcher.fetch("https://host.example/flaky")
    assert resp.status == 200 and resp.json() == {"ok": True}
    assert clock.sleeps == [1.0, 2.0]  # backoff between the three attempts


def test_persistent_server_error_raises_fetch_failed():
    clock = FakeClock()
    fetcher = Fetcher(
        transport=_transport_serving(
            {"https://host.example/robots.txt": _resp(404), "https://host.example/dead": _resp(503)}
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    with pytest.raises(FetchFailed):
        fetcher.fetch("https://host.example/dead")
    assert len(clock.sleeps) == 2  # 2 retries, backoff recorded


def test_rate_limit_sleeps_between_same_host_hits():
    clock = FakeClock()
    responses = {
        "https://host.example/robots.txt": _resp(404),
        "https://host.example/a": _resp(200),
        "https://host.example/b": _resp(200),
    }
    fetcher = Fetcher(
        transport=_transport_serving(responses),
        clock=clock,
        sleep=clock.sleep,
        min_host_interval=5.0,
    )
    fetcher.fetch("https://host.example/a")  # first hit: no sleep
    fetcher.fetch("https://host.example/b")  # second hit within interval: sleeps
    assert 4.0 <= clock.sleeps[-1] <= 5.0


def test_4xx_is_an_answer_not_a_failure():
    fetcher = Fetcher(
        transport=_transport_serving(
            {
                "https://host.example/robots.txt": _resp(404),
                "https://host.example/missing": _resp(404),
            }
        )
    )
    assert fetcher.fetch("https://host.example/missing").status == 404


def test_fetch_rejects_invalid_url_without_host():
    fetcher = Fetcher(transport=_transport_serving({}))
    assert fetcher.allowed("not-a-url") is False


def test_redirects_are_robots_checked_per_hop():
    # Gate round-6: an allowed URL redirecting to a disallowed host must raise —
    # urllib's auto-redirect would silently bypass the destination's robots.
    robots_a = b"User-agent: *\nDisallow: /\n"  # host A disallows everything
    fetcher = Fetcher(
        transport=_transport_serving(
            {
                "https://a.example/robots.txt": _resp(200, robots_a),
                "https://b.example/robots.txt": _resp(404),
                "https://b.example/target": _resp(
                    302,
                    headers={"location": "https://a.example/secret"},
                    url="https://b.example/target",
                ),
            }
        )
    )
    # b.example allows; the 302 points at a.example which disallows all.
    with pytest.raises(RobotsDisallowed):
        fetcher.fetch("https://b.example/target")


def test_allowed_redirect_is_followed_with_robots_check():
    body = b'{"moved": true}'
    clock = FakeClock()
    fetcher = Fetcher(
        transport=_transport_serving(
            {
                "https://a.example/robots.txt": _resp(404, url="https://a.example/robots.txt"),
                "https://b.example/robots.txt": _resp(404, url="https://b.example/robots.txt"),
                "https://a.example/old": _resp(301, headers={"location": "https://b.example/new"}, url="https://a.example/old"),
                "https://b.example/new": _resp(200, body, url="https://b.example/new"),
            }
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    resp = fetcher.fetch("https://a.example/old")
    assert resp.status == 200 and resp.json() == {"moved": True}


def test_three_hop_redirect_chain_succeeds():
    # Gate round-6: redirect hops must not consume the retry budget — three hops
    # then a 200 lands, despite _MAX_ATTEMPTS == 3.
    responses = {
        "https://h.example/robots.txt": _resp(404, url="https://h.example/robots.txt"),
        "https://h.example/1": _resp(301, headers={"location": "/2"}, url="https://h.example/1"),
        "https://h.example/2": _resp(302, headers={"location": "/3"}, url="https://h.example/2"),
        "https://h.example/3": _resp(302, headers={"location": "/final"}, url="https://h.example/3"),
        "https://h.example/final": _resp(200, b'{"arrived": true}', url="https://h.example/final"),
    }
    clock = FakeClock()
    fetcher = Fetcher(transport=_transport_serving(responses), clock=clock, sleep=clock.sleep)
    resp = fetcher.fetch("https://h.example/1")
    # Every hop was throttled — hops are real requests (round-5 gate review).
    assert len(clock.sleeps) >= 3
    assert resp.status == 200 and resp.json() == {"arrived": True}


def test_robots_redirect_destination_rules_apply():
    # Gate round-6: a robots.txt that REDIRECTS must yield the destination's
    # policy — an empty redirect body must not read as "unrestricted".
    robots_b = b"User-agent: *\nDisallow: /\n"
    clock = FakeClock()
    fetcher = Fetcher(
        transport=_transport_serving(
            {
                "https://a.example/robots.txt": _resp(
                    301,
                    headers={"location": "https://b.example/robots.txt"},
                    url="https://a.example/robots.txt",
                ),
                "https://b.example/robots.txt": _resp(200, robots_b, url="https://b.example/robots.txt"),
            }
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    assert fetcher.allowed("https://a.example/anything") is False


def test_schemes_beyond_http_https_are_refused():
    fetcher = Fetcher(transport=_transport_serving({}))
    with pytest.raises(FetchFailed, match="scheme"):
        fetcher.fetch("ftp://host.example/file")
    with pytest.raises(FetchFailed, match="scheme"):
        fetcher.fetch("file:///etc/passwd")
