"""LLM gateway — fake transport + injected cache; budget and validation paths."""

import json
import urllib.request

import pytest

from substrate.sources.llm import PROMPT_VERSION, BudgetExceeded, LlmGateway
from substrate.sources.press import FundingExtract


class ChatResponse:
    """Mimics the OpenAI-compatible envelope the gateway parses."""

    @staticmethod
    def envelope(company="Acme Corp", domain="acme.com", announced="2026-11-06", tokens=1000):
        content = json.dumps(
            {
                "company_name": company,
                "domain": domain,
                "round_type": "series_a",
                "amount_usd": 12_000_000,
                "announced_on": announced,
            }
        )
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": tokens},
        }


def _gateway(cache: dict, budget: float = 5.0, tokens: int = 1_000_000):
    def transport(request: urllib.request.Request):
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/chat/completions")
        body = json.loads(request.data)
        assert body["response_format"] == {"type": "json_object"}
        # The invariant in test form: the prompt asks for extraction, never identity.
        assert "identity" not in body["messages"][0]["content"].lower()
        resp = ChatResponse.envelope(tokens=tokens)
        return 200, json.dumps(resp).encode()

    return LlmGateway(
        base_url="https://llm.example/v1",
        model="extractor-1",
        api_key="env-only",
        run_budget_usd=budget,
        price_per_mtok_in=1.0,
        price_per_mtok_out=1.0,
        transport=transport,
        ), cache


def test_extract_success_and_cache_roundtrip():
    gateway, cache = _gateway({})
    lookups = {"hits": 0}

    def lookup(key):
        lookups["hits"] += 1
        return cache.get(key)

    def store(key, response, cost):
        cache[key] = response

    extract = gateway.extract_json(
        "funding_event_v1",
        {"title": "Acme raises $12M Series A", "url": "https://press.example/1"},
        FundingExtract,
        cache_lookup=lookup,
        cache_store=store,
    )
    assert extract is not None and extract.company_name == "Acme Corp"
    assert extract.amount_usd == 12_000_000
    assert gateway.calls_made == 1

    # Second identical input: cache hit, $0, no call.
    again = gateway.extract_json(
        "funding_event_v1",
        {"title": "Acme raises $12M Series A", "url": "https://press.example/1"},
        FundingExtract,
        cache_lookup=lookup,
        cache_store=store,
    )
    assert again is not None
    assert gateway.cache_hits == 1 and gateway.calls_made == 1


def test_budget_ceiling_is_fail_closed():
    gateway, _ = _gateway({}, budget=0.5, tokens=1_000_000)  # 2M tokens @ $1/M = $2 > $0.5

    def lookup(key):
        return None

    def store(key, response, cost):
        pass

    with pytest.raises(BudgetExceeded, match="fail-closed"):
        gateway.extract_json(
            "funding_event_v1",
            {"title": "huge item"},
            FundingExtract,
            cache_lookup=lookup,
            cache_store=store,
        )


def test_malformed_extraction_returns_none():
    def transport(request: urllib.request.Request):
        resp = {
            "choices": [{"message": {"content": "not-json"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return 200, json.dumps(resp).encode()

    gateway = LlmGateway(
        base_url="https://llm.example/v1", model="m", api_key="k",
        run_budget_usd=10, transport=transport,
    )
    out = gateway.extract_json(
        "funding_event_v1", {"title": "garbage"}, FundingExtract,
        cache_lookup=lambda k: None, cache_store=lambda k, r, c: None,
    )
    assert out is None  # skipped, never repaired by guessing


def test_missing_env_config_fails_loudly(monkeypatch):
    monkeypatch.delenv("SUBSTRATE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SUBSTRATE_LLM_MODEL", raising=False)
    with pytest.raises(SystemExit, match="SUBSTRATE_LLM"):
        LlmGateway()


def test_prompt_version_is_pinned():
    # The extraction contract is versioned; a bump invalidates the whole cache.
    assert PROMPT_VERSION == "2026-11-15"


def test_zero_budget_never_dispatches():
    # Gate round-5: budget must be checked BEFORE the provider is called — a
    # rejected request never reaches the transport.
    calls = {"n": 0}

    def transport(request: urllib.request.Request):
        calls["n"] += 1
        return 200, json.dumps(ChatResponse.envelope(tokens=1)).encode()

    gateway = LlmGateway(
        base_url="https://llm.example/v1", model="m", api_key="k",
        run_budget_usd=0.0, price_per_mtok_in=1.0, price_per_mtok_out=1.0,
        transport=transport,
    )
    with pytest.raises(BudgetExceeded, match="pre-dispatch"):
        gateway.extract_json(
            "funding_event_v1", {"title": "x"}, FundingExtract,
            cache_lookup=lambda k: None, cache_store=lambda k, r, c: None,
        )
    assert calls["n"] == 0  # the provider was never called

    # Bounded completions: the request carries max_tokens.
    gateway2 = LlmGateway(
        base_url="https://llm.example/v1", model="m", api_key="k",
        run_budget_usd=10.0, price_per_mtok_in=1.0, price_per_mtok_out=1.0,
        transport=transport,
    )

    captured: dict[str, object] = {}

    def capturing_transport(request: urllib.request.Request):
        captured.update(json.loads(request.data))
        return 200, json.dumps(ChatResponse.envelope(tokens=1)).encode()

    gateway2.transport = capturing_transport
    gateway2.extract_json(
        "funding_event_v1", {"title": "x"}, FundingExtract,
        cache_lookup=lambda k: None, cache_store=lambda k, r, c: None,
    )
    assert captured.get("max_tokens") == gateway2.MAX_COMPLETION_TOKENS


def test_insufficient_budget_for_worst_case_rejects_pre_dispatch():
    # Gate round-6: a positive-but-insufficient budget must reject BEFORE the
    # provider is called (worst-case reservation, not post-hoc charging).
    calls = {"n": 0}

    def transport(request: urllib.request.Request):
        calls["n"] += 1
        return 200, json.dumps(ChatResponse.envelope(tokens=1)).encode()

    # Worst case ≈ $0.05 completion reserve alone at $0.60/Mtok... make prices
    # harsh so a $0.01 ceiling cannot cover the capped completion.
    gateway = LlmGateway(
        base_url="https://llm.example/v1", model="m", api_key="k",
        run_budget_usd=0.01, price_per_mtok_in=1.0, price_per_mtok_out=100.0,
        transport=transport,
    )
    with pytest.raises(BudgetExceeded, match="worst-case"):
        gateway.extract_json(
            "funding_event_v1", {"title": "x"}, FundingExtract,
            cache_lookup=lambda k: None, cache_store=lambda k, r, c: None,
        )
    assert calls["n"] == 0


def test_missing_usage_fails_closed_accounting():
    # Gate round-6: a response without usage must be charged the worst case —
    # missing accounting must never read as zero spend.
    def transport(request: urllib.request.Request):
        resp = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "company_name": "Acme Corp",
                                "announced_on": "2026-11-06",
                                "round_type": "seed",
                                "amount_usd": 1_000_000,
                            }
                        )
                    }
                }
            ]
        }
        return 200, json.dumps(resp).encode()

    gateway = LlmGateway(
        base_url="https://llm.example/v1", model="m", api_key="k",
        run_budget_usd=10.0, price_per_mtok_in=1.0, price_per_mtok_out=100.0,
        transport=transport,
    )
    assert gateway.extract_json(
        "funding_event_v1", {"title": "x"}, FundingExtract,
        cache_lookup=lambda k: None, cache_store=lambda k, r, c: None,
    ) is not None
    assert gateway.ledger.spent_usd > 0  # worst case charged, not zero
