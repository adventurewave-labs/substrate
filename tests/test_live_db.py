"""Live-Postgres round-trip tests — skipped unless SUBSTRATE_TEST_DATABASE_URL is set.

No local Postgres on this machine (rig law: the Mac is a control plane, no daemons);
these run against the managed instance at the W2 bootstrap and in CI/remote once a
server exists. The gate reviewer flagged the DB path as untested — this is the seam
the live evidence rides through.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SUBSTRATE_TEST_DATABASE_URL"),
    reason="SUBSTRATE_TEST_DATABASE_URL not set — live DB path runs on the remote plane",
)

CSV = """Contact ID,First Name,Last Name,Email,Title,Account Name
003aa,Ann,Lee,a@acme.com,VP Eng,Acme
003bb,Anne,Lee,a@acme.com,Engineer,Acme
003cc,Bo,Wu,bo@beta.com,CTO,Beta
"""


@pytest.fixture
def dbConn():
    import psycopg

    from substrate import db

    conn = psycopg.connect(os.environ["SUBSTRATE_TEST_DATABASE_URL"])
    db.run_migrations(conn)  # idempotent — brings the instance to head
    yield conn
    conn.close()


def _fresh_tenant(conn, name: str):
    from substrate.store import ensure_tenant

    conn.execute("DELETE FROM tenants WHERE name = %s", (name,))
    conn.commit()
    return ensure_tenant(conn, name, "csv")


def test_import_er_audit_roundtrip(dbConn):
    from substrate.er.engine import (
        cluster_map_for,
        run_audit,
        run_er_v0,
    )
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = "live-test-roundtrip"
    tenant_id = _fresh_tenant(conn, tenant)

    rows = [
        {
            "contact_id": "003aa", "email": "a@acme.com", "name_given": "Ann",
            "name_family": "Lee", "title": "VP Eng", "org_name": "Acme",
        },
        {
            "contact_id": "003bb", "email": "a@acme.com", "name_given": "Anne",
            "name_family": "Lee", "title": "Engineer", "org_name": "Acme",
        },
        {
            "contact_id": "003cc", "email": "bo@beta.com", "name_given": "Bo",
            "name_family": "Wu", "title": "CTO", "org_name": "Beta",
        },
    ]
    with conn.transaction():
        persist_contacts(conn, tenant_id, rows, system="csv")

    # dry-run writes nothing
    dry = run_er_v0(conn, tenant_id, dry_run=True)
    assert dry.auto_merge == 1  # R1: a@acme.com + Lee/Lee
    assert dry.review == 0
    n_decisions = conn.execute(
        "SELECT count(*) FROM merge_decisions WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()[0]
    assert n_decisions == 0

    # real run writes decisions + rule, refuses duplicate non-forced rerun
    stats = run_er_v0(conn, tenant_id)
    assert stats.auto_merge == 1
    decision = conn.execute(
        "SELECT decision, rule FROM merge_decisions WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    assert decision[0] == "auto_merge" and decision[1] == "R1_exact_email_same_family"

    # cluster view collapses the dup
    cmap = cluster_map_for(conn, tenant_id)
    assert len(set(cmap.values())) == 2  # lee-cluster + Bo Wu

    # audit math on the merged view
    report, _page = run_audit(conn, tenant)
    assert report["contacts_total"] == 3
    assert report["clusters"] == 2
    assert report["duplicates_collapsed"] == 1

    # rerun without force is refused; with force it replaces (idempotent outcome)
    from substrate.er.engine import FEATURESET_VERSION

    with pytest.raises(SystemExit, match="force"):
        run_er_v0(conn, tenant_id)
    again = run_er_v0(conn, tenant_id, force=True)
    assert again.auto_merge == 1
    n_after = conn.execute(
        "SELECT count(*) FROM merge_decisions WHERE tenant_id = %s "
        "AND featureset_version = %s AND decision = 'auto_merge'",
        (tenant_id, FEATURESET_VERSION),
    ).fetchone()[0]
    assert n_after == 1

    # queue carries only REVIEW pairs — R1 is auto, so nothing queues here
    n_queue = conn.execute(
        "SELECT count(*) FROM review_queue WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()[0]
    assert n_queue == 0


def test_cli_audit_suffix_guard():
    from substrate.cli import main

    with pytest.raises(SystemExit, match="must end with .json"):
        main(["audit", "--tenant", "x", "--out", "report.html"])
