import json
from pathlib import Path

import pytest

from substrate.sources.careers import (
    classify_function,
    crawl_careers,
    parse_ashby,
    parse_greenhouse,
    parse_lever,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_greenhouse_fixture_parses_with_functions():
    postings = parse_greenhouse(_load("greenhouse.json"))
    by_title = {p["title_norm"]: p for p in postings}
    assert len(postings) == 3
    assert by_title["Senior Backend Engineer"]["function"] == "engineering"
    assert by_title["Account Executive, Mid-Market"]["function"] == "sales"
    assert by_title["Chief of Staff"]["function"] is None  # unclassifiable: None, never guessed
    assert by_title["Senior Backend Engineer"]["location"] == "New York"
    assert by_title["Senior Backend Engineer"]["posted_at"] is not None


def test_lever_fixture_parses():
    postings = parse_lever(_load("lever.json"))
    by_title = {p["title_norm"]: p for p in postings}
    assert by_title["Staff Software Engineer"]["function"] == "engineering"
    assert by_title["Staff Software Engineer"]["location"] == "Remote EU"
    assert by_title["Staff Software Engineer"]["posted_at"] is not None
    assert by_title["VP Marketing"]["function"] == "marketing"


def test_ashby_fixture_parses():
    postings = parse_ashby(_load("ashby.json"))
    by_title = {p["title_norm"]: p for p in postings}
    assert by_title["Product Designer"]["function"] == "product"
    assert by_title["Customer Success Manager"]["function"] == "customer_success"


def test_shape_changes_fail_loudly():
    with pytest.raises(ValueError, match="shape changed|not a dict"):
        parse_greenhouse({"jobs": "gone"})
    with pytest.raises(ValueError):
        parse_lever({"not": "a list"})
    with pytest.raises(ValueError):
        parse_ashby({"jobs": [{"title": "x"}]})  # missing jobUrl


def test_crawl_careers_dispatches_by_platform():
    from substrate.sources.http import FetchResponse

    served = {
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": FetchResponse(
            url="x", status=200, body=json.dumps(_load("greenhouse.json")).encode()
        )
    }

    class NoRobots:
        def fetch(self, url, headers=None):
            if url in served:
                return served[url]
            return FetchResponse(url=url, status=404, body=b"")

    postings = crawl_careers(NoRobots(), board="acme", platform="greenhouse")  # type: ignore[arg-type]
    assert len(postings) == 3


def test_function_classifier_is_conservative():
    assert classify_function("Sales Development Rep") == "sales"
    assert classify_function("Data Engineer") == "engineering"
    assert classify_function("Paralegal") is None


def test_normalize_domain_strips_and_validates():
    from substrate.sources.crawl import normalize_domain

    assert normalize_domain("https://www.acme.com/about") == "acme.com"
    assert normalize_domain("ACME.com/") == "acme.com"
    assert normalize_domain("not a domain") is None
    assert normalize_domain("acme") is None  # no TLD
    assert normalize_domain("") is None


def test_domain_corroboration_is_precise():
    from substrate.sources.crawl import domain_corroborated

    # URL host equality (with www stripped)
    assert domain_corroborated("acme.com", "", "https://acme.com/blog/series-a") is True
    assert domain_corroborated("acme.com", "", "https://www.acme.com/blog") is True
    # Title word-boundary match
    assert domain_corroborated("acme.com", "title mentions acme.com", "") is True
    # A hallucinated domain must not steer claims onto a real org (gate round 1).
    assert domain_corroborated("acme.com", "Beta Industries closes seed round") is False
    assert domain_corroborated("not a domain", "anything") is False
    # Round-3 precision: substrings and ccTLD collisions cannot corroborate.
    assert domain_corroborated("acme.com", "", "https://notacme.com/post") is False
    assert domain_corroborated("acme.com", "we love acme.community", "") is False
    assert domain_corroborated("victim.co.uk", "", "https://news.example.co.uk/story") is False


def test_malformed_nested_shapes_raise_valueerror():
    # Gate round-5: a dict-shaped departments list must raise ValueError (the
    # board-isolation handler's type), not KeyError — so one malformed board fails
    # alone instead of aborting the tenant crawl.
    payload = {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://x/1",
                         "departments": {"name": "Engineering"}, "offices": []}]}
    with pytest.raises(ValueError, match="departments is not a list"):
        parse_greenhouse(payload)
    payload2 = {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://x/1",
                          "departments": [], "offices": {"name": "NYC"}}]}
    with pytest.raises(ValueError, match="offices is not a list"):
        parse_greenhouse(payload2)


def test_lever_timestamp_overflow_raises_valueerror():
    # Gate round-6: numeric garbage like 1e100 must raise ValueError (board
    # isolation catches it) — never OverflowError, which aborts the tenant crawl.
    with pytest.raises(ValueError, match="createdAt out of range"):
        parse_lever([{"id": "x", "text": "Engineer", "hostedUrl": "https://j.example/x",
                      "createdAt": 10_000_000_000_000_000_000_000_000_000_000_000}])


def test_name_corroboration_guard():
    # Round-4 guard, finally unit-tested (gate round-6 note): the LLM-supplied
    # company name must appear word-bounded in the source title.
    from substrate.sources.crawl import name_corroborated

    assert name_corroborated("Acme Corp", "Acme Corp raises $12M Series A") is True
    assert name_corroborated("acme corp", "ACME CORP closes seed round") is True
    assert name_corroborated("Acme Corp", "Beta Industries closes seed round") is False
    assert name_corroborated("Acme", "AcmeCorp ships something") is False  # no word boundary
    assert name_corroborated("", "anything") is False
