import json

import pytest

from substrate.audit.report import build_report, render_html
from substrate.er.blocking import PersonRecord, slugify


def _p(pid, *, emails=(), given=None, family=None, employer=None, has_title=False):
    return PersonRecord(
        person_id=pid,
        emails=list(emails),
        name_given=given,
        name_family=family,
        employer_slug=slugify(employer) if employer else None,
        email_domain=emails[0].split("@", 1)[1] if emails else None,
        has_title=has_title,
    )


def test_report_math_with_clusters():
    persons = [
        _p("1", emails=("a@acme.com",), given="Ann", family="Lee", employer="Acme", has_title=True),
        _p("2", emails=("a@acme.com",), given="Ann", family="Lee", employer="Acme"),
        _p("3", emails=("bob@beta.com",), family="Wu"),  # no org anchor
    ]
    cluster_map = {"1": "1", "2": "1", "3": "3"}
    report = build_report("acme", persons, cluster_map)

    assert report.contacts_total == 3
    assert report.clusters == 2
    assert report.duplicates_collapsed == 1
    assert report.contactable_rate == 1.0
    assert report.org_anchored_rate == round(2 / 3, 4)
    assert report.shared_email_collisions == 1  # a@acme.com on two persons
    assert report.title_population == round(1 / 3, 4)  # actual titles, not name presence


def test_report_empty_tenant_is_an_error():
    with pytest.raises(ValueError, match="empty tenant"):
        build_report("ghost", [], {})


def test_report_marks_unmeasurable_honestly():
    persons = [_p("1", emails=("a@x.com",), family="Lee")]
    payload = build_report("acme", persons, {"1": "1"}).as_dict()
    assert "stale_title_pct" in payload["not_yet_measurable"]
    assert "champions_moved_90d" in payload["not_yet_measurable"]


def test_json_and_html_render():
    persons = [_p("1", emails=("a@x.com",), given="Ann", family="Lee", employer="Acme")]
    report = build_report("acme", persons, {"1": "1"})
    payload = json.loads(report.to_json())
    assert payload["tenant"] == "acme"

    page = render_html(report)
    assert "Graph Audit" in page
    assert "measured, not modeled" in page
    assert "stale titles" in page  # pending cards present
