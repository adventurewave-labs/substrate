import json
from datetime import date
from pathlib import Path

import pytest

from substrate.sources.edgar import parse_efts_response, sec_user_agent
from substrate.sources.http import FetchResponse
from substrate.sources.press import funding_candidates, parse_rss

FIXTURES = Path(__file__).parent / "fixtures"


def test_efts_fixture_parses_funding_events():
    payload = json.loads((FIXTURES / "efts.json").read_text())
    events, total = parse_efts_response(payload)
    assert len(events) == 2  # non-Form-D and non-date hits are skipped, never guessed
    assert total == 5  # fixture reports 5 matches; truncation must be counted, not dropped
    by_name = {e["company_name"]: e for e in events}
    acme = by_name["Acme Corp, Inc."]
    assert acme["cik"] == "0001234567"
    assert acme["announced_on"] == date(2026, 11, 1)
    assert acme["url"].startswith("https://www.sec.gov/Archives/edgar/data/0001234567/")
    assert acme["amount_usd"] is None  # XML drill-down is a later enhancement
    assert acme["round_type"] is None


def test_efts_shape_changes_fail_loudly():
    with pytest.raises(ValueError, match="shape changed|not a dict"):
        parse_efts_response({"hits": {"hits": "gone"}})
    with pytest.raises(ValueError):
        parse_efts_response({"no_hits": True})


def test_sec_user_agent_requires_contact(monkeypatch):
    monkeypatch.delenv("SUBSTRATE_SEC_CONTACT", raising=False)
    with pytest.raises(SystemExit, match="SUBSTRATE_SEC_CONTACT"):
        sec_user_agent()
    monkeypatch.setenv("SUBSTRATE_SEC_CONTACT", "Ops <ops@example.com>")
    assert "ops@example.com" in sec_user_agent()


# ---- press ----


def _rss_response() -> FetchResponse:
    return FetchResponse(
        url="https://press.example/feed", status=200, body=(FIXTURES / "press.xml").read_bytes()
    )


def test_rss_parses_items():
    items = parse_rss(_rss_response())
    assert len(items) == 3  # malformed item without link is dropped
    by_title = {i.title: i for i in items}
    assert by_title["Acme Corp raises $12M Series A to automate GTM identity"].published is not None


def test_funding_gate_keeps_budget_honest():
    items = parse_rss(_rss_response())
    candidates = funding_candidates(items)
    titles = {c.title for c in candidates}
    assert "Acme Corp raises $12M Series A to automate GTM identity" in titles
    assert "Beta Industries closes $4.5M seed round" in titles
    # The product-launch item pays $0 in LLM calls — the gate did its job.
    assert "Acme Corp ships new integration marketplace" not in titles
