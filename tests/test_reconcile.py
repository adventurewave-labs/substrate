import json

from substrate.reconcile import build_contact_report


def _rows():
    return [
        {
            "email": "a@x.com",
            "title": "VP Eng",
            "org_name": "Acme",
            "account_id": "1",
            "name_given": "A",
            "name_family": "B",
        },
        {
            "email": "A@X.com",
            "title": None,
            "org_name": "Acme",
            "account_id": "1",
            "name_given": "A",
            "name_family": "B",
        },
        {
            "email": "b@y.com",
            "title": "CTO",
            "org_name": "Beta",
            "account_id": "2",
            "name_given": "C",
            "name_family": "D",
        },
    ]


def test_report_math():
    skipped = [(4, "no stable identity key (need contact_id or email)")]
    report = build_contact_report("contact", _rows(), skipped)

    assert report.rows_read == 4
    assert report.rows_parsed == 3
    assert report.rows_skipped == 1
    assert report.skip_reasons["no stable identity key (need contact_id or email)"] == 1

    # emails are lowercased before counting: a@x.com appears twice
    assert report.distinct_emails == 2
    assert report.duplicate_email_rows == 1

    assert report.field_population["title"] == round(2 / 3, 4)
    assert report.field_population["org_name"] == 1.0
    assert report.field_population["email"] == 1.0


def test_report_json_serializable():
    report = build_contact_report("contact", _rows(), [])
    payload = json.loads(report.to_json())
    assert payload["object_name"] == "contact"
    assert payload["rows_parsed"] == 3
    assert isinstance(payload["skip_reasons"], dict)


def test_blank_and_none_count_as_unpopulated():
    rows = [
        {
            "email": "a@x.com",
            "title": "  ",
            "org_name": None,
            "account_id": "",
            "name_given": "A",
            "name_family": "B",
        }
    ]
    report = build_contact_report("contact", rows, [])
    assert report.field_population["title"] == 0.0
    assert report.field_population["org_name"] == 0.0
    assert report.field_population["account_id"] == 0.0
