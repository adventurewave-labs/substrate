from substrate.importers.csv_import import canonicalize_header, parse_contacts

SFDC_EXPORT = """Contact ID,First Name,Last Name,Email,Title,Account Name,AccountId,Notes
003xx,Ada,Smith, A@Example.com ,VP Engineering,Acme Corp,001a,met at conference
003yy,Bob,Jones,b@example.com,,Beta Inc,001b,
,Cara,Lee,c@example.com,CTO,Gamma LLC,001c,
,Dan,Moore,,VP Sales,Delta Co,001d,
003zz,Eve,null,not-an-email,CTO,Epsilon,001e,
"""


def test_parse_contacts_sfdc_export():
    rows, skipped = parse_contacts(SFDC_EXPORT)

    assert len(rows) == 3
    assert len(skipped) == 2

    ada = rows[0]
    assert ada["contact_id"] == "003xx"
    assert ada["email"] == "a@example.com"  # stripped + lowercased
    assert ada["name_given"] == "Ada"
    assert ada["org_name"] == "Acme Corp"
    assert ada["account_id"] == "001a"
    assert ada["title"] == "VP Engineering"

    # Row 3 (Cara): no contact id but a valid email — email is a stable identity key.
    assert rows[2].get("contact_id") is None
    assert rows[2]["email"] == "c@example.com"


def test_skip_reasons():
    _, skipped = parse_contacts(SFDC_EXPORT)
    reasons = {reason for _, reason in skipped}
    assert any("no stable identity key" in r for r in reasons)
    assert any("invalid email" in r for r in reasons)


def test_unknown_columns_ignored():
    rows, _ = parse_contacts(SFDC_EXPORT)
    assert "notes" not in rows[0]  # ignored, not fatal


def test_canonicalize_header_aliases():
    assert canonicalize_header("Job Title") == "title"
    assert canonicalize_header("Company") == "org_name"
    assert canonicalize_header("hs_object_id") == "contact_id"
    assert canonicalize_header("Totally Custom") is None


def test_hubspot_style_headers():
    hs_csv = """First Name,Last Name,Email,Job Title,Company
Gita,Rao,gita@example.com,Head of RevOps,Rao Systems
"""
    rows, skipped = parse_contacts(hs_csv)
    assert skipped == []
    assert rows[0]["name_given"] == "Gita"
    assert rows[0]["title"] == "Head of RevOps"
    assert rows[0]["org_name"] == "Rao Systems"
