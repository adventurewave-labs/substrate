"""LLM extraction gateway: env-configured, cached, budget-capped, structured.

Hard lines:
  * extraction and normalization ONLY — this module must never touch identity
  * aggressive caching (content-hash key) — reruns and identical text cost $0
  * a hard per-run budget ceiling, fail-closed: exceeding it aborts the extraction,
    never silently degrades
  * provider-agnostic: any OpenAI-compatible chat endpoint (base URL + model + key
    via SUBSTRATE_LLM_* env)
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

PROMPT_VERSION = "2026-11-15"  # bump when the extraction contract changes

_SYSTEM_PROMPT = {
    "funding_event_v1": (
        "You extract structured funding-event data from press items. "
        "Return ONLY a JSON object with keys: company_name (string), domain "
        "(string or null), round_type (one of: pre_seed, seed, series_a, series_b, "
        "series_c, series_d, growth, debt, grant, or null), amount_usd (number or "
        "null), announced_on (ISO date YYYY-MM-DD). Use null when the text does not "
        "state a value — never guess. Company name and domain must appear in or be "
        "directly implied by the text."
    ),
}


class BudgetExceeded(Exception):
    pass


@dataclass
class SpendLedger:
    """Per-run cost accounting against the configured ceiling."""

    limit_usd: float
    spent_usd: float = 0.0

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        if self.spent_usd > self.limit_usd:
            raise BudgetExceeded(
                f"LLM budget exceeded: ${self.spent_usd:.4f} > ${self.limit_usd:.2f} ceiling — "
                "aborting extraction (fail-closed, per plan §4 budget rule)"
            )


T = TypeVar("T", bound=BaseModel)

Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def _stdlib_transport(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:  # noqa: S310 — env-configured base URL
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class LlmGateway:
    """OpenAI-compatible chat-completions client with cache + budget."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        run_budget_usd: float | None = None,
        price_per_mtok_in: float | None = None,
        price_per_mtok_out: float | None = None,
        transport: Transport | None = None,
        database_url: str | None = None,
    ) -> None:
        self._database_url = database_url  # None → SUBSTRATE_DATABASE_URL (settings)
        self.base_url = (base_url or os.environ.get("SUBSTRATE_LLM_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("SUBSTRATE_LLM_MODEL", "")
        self._api_key = api_key or os.environ.get("SUBSTRATE_LLM_API_KEY", "")
        self.price_in = price_per_mtok_in if price_per_mtok_in is not None else float(
            os.environ.get("SUBSTRATE_LLM_PRICE_PER_MTOK_IN", "0.15")
        )
        self.price_out = price_per_mtok_out if price_per_mtok_out is not None else float(
            os.environ.get("SUBSTRATE_LLM_PRICE_PER_MTOK_OUT", "0.60")
        )
        self.transport = transport or _stdlib_transport
        self.ledger = SpendLedger(
            limit_usd=run_budget_usd if run_budget_usd is not None else float(
                os.environ.get("SUBSTRATE_LLM_RUN_BUDGET_USD", "5.00")
            )
        )
        self.cache_hits = 0
        self.calls_made = 0
        if not self.base_url or not self.model:
            raise SystemExit(
                "SUBSTRATE_LLM_BASE_URL and SUBSTRATE_LLM_MODEL are required for extraction"
            )

    # -- public -----------------------------------------------------------------

    def extract_json(
        self,
        prompt_kind: str,
        prompt_input: dict[str, Any],
        result_type: type[T],
        cache_lookup: Callable[[str], Any | None] | None = None,
        cache_store: Callable[[str, dict[str, Any], float], None] | None = None,
    ) -> T | None:
        """Extract one typed object from unstructured input. None = the model could
        not produce a valid object for this input (counted, not guessed)."""
        system = _SYSTEM_PROMPT.get(prompt_kind)
        if system is None:
            raise ValueError(f"unknown prompt kind {prompt_kind!r}")
        canonical = json.dumps(prompt_input, sort_keys=True, ensure_ascii=False)
        cache_key = hashlib.sha256(
            f"{self.model}|{PROMPT_VERSION}|{prompt_kind}|{canonical}".encode()
        ).hexdigest()

        lookup = cache_lookup or self.lookup_db_cache
        store = cache_store or self.store_db_cache
        cached = lookup(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return self._validate(cached, result_type)

        response_payload, cost = self._call(system, canonical)
        self.calls_made += 1
        content = self._content_of(response_payload)
        if content is None:
            self.ledger.charge(cost)
            return None
        # Cache before charging: the call is paid for either way — a rerun must hit
        # the cache instead of paying twice when the budget ceiling trips.
        store(cache_key, content, cost)
        self.ledger.charge(cost)
        return self._validate(content, result_type)

    # -- internals ---------------------------------------------------------------

    # Completion cap keeps worst-case cost bounded and checkable pre-dispatch.
    MAX_COMPLETION_TOKENS = 500

    # Message-framing overhead per chat message (role tags, separators), in tokens.
    FRAMING_TOKENS_PER_MESSAGE = 8

    def _worst_case_cost(self, system: str, user_content: str) -> float:
        # Provider-agnostic conservative bound: UTF-8 BYTES (a CJK char is 3 bytes
        # and can be several tokens — char counts UNDERestimate, bytes do not),
        # plus per-message framing overhead.
        prompt_bytes = (
            len(system.encode("utf-8"))
            + len(user_content.encode("utf-8"))
            + 2 * self.FRAMING_TOKENS_PER_MESSAGE
        )
        return (
            self.price_in * max(prompt_bytes, 1) / 1_000_000
            + self.price_out * self.MAX_COMPLETION_TOKENS / 1_000_000
        )

    def _call(self, system: str, user_content: str) -> tuple[dict[str, Any], float]:
        remaining = self.ledger.limit_usd - self.ledger.spent_usd
        worst_case = self._worst_case_cost(system, user_content)
        if worst_case > remaining:
            raise BudgetExceeded(
                f"request worst-case ${worst_case:.4f} exceeds remaining budget "
                f"${remaining:.4f} (ceiling ${self.ledger.limit_usd:.2f}) — rejected "
                "pre-dispatch, the provider was never called"
            )
        body = json.dumps(
            {
                "model": self.model,
                "response_format": {"type": "json_object"},
                "max_tokens": self.MAX_COMPLETION_TOKENS,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        status, raw = self.transport(request)
        if status != 200:
            raise RuntimeError(f"llm endpoint returned HTTP {status}")
        payload = json.loads(raw)
        usage = payload.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if not isinstance(prompt_tokens, (int, float)) or not isinstance(
            completion_tokens, (int, float)
        ):
            # Unaccountable call: charge the full worst case — missing usage must
            # never read as zero spend (fail-closed accounting, round-4 review).
            return payload, self._worst_case_cost(system, user_content)
        cost = (
            prompt_tokens / 1_000_000 * self.price_in
            + completion_tokens / 1_000_000 * self.price_out
        )
        return payload, cost

    @staticmethod
    def _content_of(payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        if not isinstance(content, str):
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _validate(content: dict[str, Any], result_type: type[T]) -> T | None:
        try:
            return result_type.model_validate(content)
        except ValidationError:
            return None  # invalid extraction = skipped, never repaired by guessing

    # -- default cache transport (DB) — overridable for tests -------------------

    def lookup_db_cache(self, cache_key: str) -> Any | None:
        from substrate.config import get_settings
        from substrate.db import connect

        conn = connect(self._database_url or get_settings().database_url)
        try:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE cache_key = %s", (cache_key,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def store_db_cache(self, cache_key: str, response: dict[str, Any], cost: float) -> None:
        from substrate.config import get_settings
        from substrate.db import connect

        conn = connect(self._database_url or get_settings().database_url)
        try:
            conn.execute(
                "INSERT INTO llm_cache (cache_key, model, prompt_version, response, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (cache_key) DO NOTHING",
                (cache_key, self.model, PROMPT_VERSION, json.dumps(response), cost),
            )
            conn.commit()
        finally:
            conn.close()
