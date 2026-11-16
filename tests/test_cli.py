import json

import pytest

from substrate.cli import main

CSV = """Contact ID,First Name,Last Name,Email,Title,Account Name
003aa,Nia,Okafor,nia@example.com,Director of RevOps,Okafor Labs
003bb,Omar,Perez,omar@example.com,,Perez Group
"""


def test_import_csv_dry_run(tmp_path, monkeypatch):
    # Dry run must not need a database: point DATABASE_URL at garbage to prove it.
    monkeypatch.setenv("SUBSTRATE_DATABASE_URL", "postgresql://no:such@localhost:1/none")

    src = tmp_path / "contacts.csv"
    src.write_text(CSV, encoding="utf-8")
    out = tmp_path / "report.json"

    rc = main(
        [
            "import-csv",
            "--tenant",
            "acme",
            "--contacts-file",
            str(src),
            "--report",
            str(out),
            "--dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["reconciliation"]["rows_read"] == 2
    assert payload["reconciliation"]["rows_parsed"] == 2
    assert "persistence" not in payload  # no database was touched


def test_import_csv_dry_run_with_bad_rows(tmp_path):
    src = tmp_path / "contacts.csv"
    src.write_text("Contact ID,Email\n,not-an-email\n", encoding="utf-8")
    out = tmp_path / "report.json"

    rc = main(
        [
            "import-csv",
            "--tenant",
            "acme",
            "--contacts-file",
            str(src),
            "--report",
            str(out),
            "--dry-run",
        ]
    )

    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["reconciliation"]["rows_skipped"] == 1
    assert payload["reconciliation"]["rows_parsed"] == 0
    assert payload["reconciliation"]["field_population"].get("email", 0.0) == 0.0


def test_audit_rejects_non_json_out_before_touching_a_database(monkeypatch):
    # Guard fires before any connect: garbage DATABASE_URL proves it.
    monkeypatch.setenv("SUBSTRATE_DATABASE_URL", "postgresql://no:such@localhost:1/none")
    with pytest.raises(SystemExit, match="must end with .json"):
        main(["audit", "--tenant", "x", "--out", "report.html"])


def test_detect_rejects_contradictory_flags(monkeypatch, tmp_path):
    # Both flags together does nothing useful — must fail before touching a DB.
    monkeypatch.setenv("SUBSTRATE_DATABASE_URL", "postgresql://no:such@localhost:1/none")
    with pytest.raises(SystemExit, match="mutually exclusive"):
        main([
            "detect", "--tenant", "x",
            "--detect-only", "--deliver-only",
            "--report", str(tmp_path / "r.json"),
        ])
