"""Live-Postgres round-trip tests — skipped unless SUBSTRATE_TEST_DATABASE_URL is set.

No local Postgres on this machine (rig law: the Mac is a control plane, no daemons);
these run against the managed instance at the W2 bootstrap and in CI/remote once a
server exists. The gate reviewer flagged the DB path as untested — this is the seam
the live evidence rides through.
"""

from __future__ import annotations

import os

import psycopg
import pytest


class RecordingSink:
    """Module-level: configured, records payloads, delivers."""

    configured = True

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def deliver(self, payload: dict) -> bool:
        self.payloads.append(payload)
        return True


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
    from uuid import uuid4

    from substrate.er.engine import (
        cluster_map_for,
        run_audit,
        run_er_v0,
    )
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"live-{uuid4().hex[:8]}"  # unique per run — no cleanup/FK/trigger tangles
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
        {
            # same email, different family — R2 REVIEW against both Lees
            "contact_id": "003dd", "email": "a@acme.com", "name_given": "Sam",
            "name_family": "Wu", "title": "Analyst", "org_name": "Acme",
        },
    ]
    with conn.transaction():
        persist_contacts(conn, tenant_id, rows, system="csv")

    # dry-run writes nothing
    dry = run_er_v0(conn, tenant_id, dry_run=True)
    assert dry.auto_merge == 1  # R1: a@acme.com + Lee/Lee
    assert dry.review == 2  # R2: Sam Wu vs Ann and Anne Lee
    n_decisions = conn.execute(
        "SELECT count(*) FROM merge_decisions WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()[0]
    assert n_decisions == 0

    # real run writes decisions + rule, refuses duplicate non-forced rerun
    stats = run_er_v0(conn, tenant_id)
    assert stats.auto_merge == 1 and stats.review == 2
    decision = conn.execute(
        "SELECT decision, rule FROM merge_decisions WHERE tenant_id = %s "
        "AND decision = 'auto_merge'",
        (tenant_id,),
    ).fetchone()
    assert decision[0] == "auto_merge" and decision[1] == "R1_exact_email_same_family"

    # cluster view collapses the dup
    cmap = cluster_map_for(conn, tenant_id)
    assert len(set(cmap.values())) == 3  # lee-cluster + Sam Wu + Bo Wu

    # audit math on the merged view
    report, _page = run_audit(conn, tenant)
    assert report["contacts_total"] == 4
    assert report["clusters"] == 3
    assert report["duplicates_collapsed"] == 1

    # rerun without force is refused; with force it replaces ALL feature rows
    # (auto_merge AND review) — no duplication (gate round-3 finding)
    from substrate.er.engine import FEATURESET_VERSION

    with pytest.raises(SystemExit, match="force"):
        run_er_v0(conn, tenant_id)
    again = run_er_v0(conn, tenant_id, force=True)
    assert again.auto_merge == 1 and again.review == 2
    n_after = conn.execute(
        "SELECT count(*) FROM merge_decisions WHERE tenant_id = %s "
        "AND featureset_version = %s",
        (tenant_id, FEATURESET_VERSION),
    ).fetchone()[0]
    assert n_after == 3  # 1 auto_merge + 2 review, not 5

    # review_queue holds each pair once; force preserves the human state
    n_queue = conn.execute(
        "SELECT count(*) FROM review_queue WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()[0]
    assert n_queue == 2



def test_careers_crawl_roundtrip(dbConn):
    """Watch list → careers crawl (fake fetcher) → postings + provenanced claims."""
    import json
    from datetime import UTC, datetime
    from pathlib import Path
    from uuid import uuid4

    from substrate.sources.crawl import crawl_careers_for_tenant
    from substrate.sources.http import FetchResponse
    from substrate.sources.writer import WriteStats

    conn = dbConn
    tenant = f"src-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    conn.execute("SELECT watch_upsert(%s, %s, %s, %s, %s, %s)",
                 (tenant_id, "acme.com", "acme", None, None, None))
    conn.commit()

    greenhouse = json.dumps(
        json.loads((Path(__file__).parent / "fixtures" / "greenhouse.json").read_text())
    ).encode()

    class FakeFetcher:
        skipped_robots = 0

        def fetch(self, url, headers=None):
            assert "boards-api.greenhouse.io" in url
            return FetchResponse(url=url, status=200, body=greenhouse)

    report = crawl_careers_for_tenant(conn, tenant_id, FakeFetcher())  # type: ignore[arg-type]
    assert report.boards_crawled == 1
    assert report.events_seen == 3
    assert report.stats.postings_written == 3
    assert report.stats.claims_written == 1  # hiring_activity supersede
    assert report.stats.orgs_created == 1

    # Idempotent replay: no duplicate postings, claim unchanged.
    replay = crawl_careers_for_tenant(conn, tenant_id, FakeFetcher())  # type: ignore[arg-type]
    assert replay.stats.postings_written == 0
    assert replay.stats.skipped_unchanged >= 1

    n_postings = conn.execute(
        "SELECT count(*) FROM job_postings WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()[0]
    assert n_postings == 3

    claim = conn.execute(
        "SELECT value_norm, source_type FROM claims WHERE tenant_id = %s "
        "AND field = 'hiring_activity'",
        (tenant_id,),
    ).fetchone()
    assert claim is not None and claim[0] == "open_postings:3" and claim[1] == "careers"

    # Feed claims land with provenance too (writer path sanity).
    from substrate.sources.feeds import coresignal_company_claims
    from substrate.sources.writer import persist_claim_drafts

    org_row = conn.execute(
        "SELECT id FROM organizations WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    drafts = coresignal_company_claims(
        {"website": "acme.com", "employees_count": 184}, org_id=org_row[0],
        retrieved_at=datetime.now(UTC),
    )
    stats = WriteStats()
    persist_claim_drafts(conn, tenant_id, drafts, stats)
    assert stats.claims_written == 1  # employee_count
    conn.commit()


def test_posting_lifecycle_roundtrip(dbConn):
    """Close on delist → resurrect on return → retitle updates in place (no double count)."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from substrate.sources.writer import (
        WriteStats,
        persist_postings,
        write_hiring_activity_claim,
    )

    conn = dbConn
    tenant = f"lc-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)
    org_id, _ = _org(conn, tenant_id, "acme.com")
    now = datetime.now(UTC)
    stats = WriteStats()

    postings = [
        {"title_norm": "Engineer", "function": "engineering",
         "url": "https://x.example/1", "posted_at": None},
        {"title_norm": "Seller", "function": "sales",
         "url": "https://x.example/2", "posted_at": None},
    ]
    persist_postings(conn, tenant_id, org_id, postings,
                     source_type="greenhouse", retrieved_at=now, stats=stats)
    write_hiring_activity_claim(conn, tenant_id, org_id, stats=stats)
    assert _open_count(conn, tenant_id, org_id) == 2
    assert _hiring_value(conn, tenant_id, org_id) == "open_postings:2"

    # Delist one → count drops
    persist_postings(conn, tenant_id, org_id, postings[:1],
                     source_type="greenhouse", retrieved_at=now, stats=WriteStats())
    write_hiring_activity_claim(conn, tenant_id, org_id, stats=WriteStats())
    assert _open_count(conn, tenant_id, org_id) == 1
    assert _hiring_value(conn, tenant_id, org_id) == "open_postings:1"

    # The delisted posting returns → resurrected, not double-counted
    persist_postings(conn, tenant_id, org_id, postings,
                     source_type="greenhouse", retrieved_at=now, stats=WriteStats())
    write_hiring_activity_claim(conn, tenant_id, org_id, stats=WriteStats())
    assert _open_count(conn, tenant_id, org_id) == 2

    # Retitled posting, same URL → updated in place; the OTHER posting must stay
    # open (it is still listed — reconciliation never closes a listed posting).
    retitled = [
        {"title_norm": "Staff Engineer", "function": "engineering",
         "url": "https://x.example/1", "posted_at": None},
        postings[1],
    ]
    persist_postings(conn, tenant_id, org_id, retitled,
                     source_type="greenhouse", retrieved_at=now, stats=WriteStats())
    assert _open_count(conn, tenant_id, org_id) == 2
    titles = [r[0] for r in conn.execute(
        "SELECT title_norm FROM job_postings WHERE tenant_id = %s "
        "AND org_id = %s AND closed_at IS NULL",
        (tenant_id, org_id)).fetchall()]
    assert sorted(titles) == ["seller", "staff-engineer"]


def _org(conn, tenant_id, domain):
    from substrate.sources.writer import resolve_org_by_domain

    return resolve_org_by_domain(conn, tenant_id, domain)


def _open_count(conn, tenant_id, org_id) -> int:
    row = conn.execute(
        "SELECT count(*) FROM job_postings WHERE tenant_id = %s "
        "AND org_id = %s AND closed_at IS NULL",
        (tenant_id, org_id)).fetchone()
    return int(row[0])


def _hiring_value(conn, tenant_id, org_id) -> str:
    row = conn.execute(
        "SELECT value_norm FROM claims WHERE tenant_id = %s AND entity_type = 'organization' "
        "AND entity_id = %s AND field = 'hiring_activity' AND superseded_by IS NULL",
        (tenant_id, org_id)).fetchone()
    return row[0] if row else ""


def test_press_roundtrip_provenance(dbConn):
    """LLM-extracted press funding → real-article URL, press_claimed tag, latest-wins claim."""
    import json
    from uuid import uuid4

    from substrate.sources.http import FetchResponse
    from substrate.sources.press import extract_funding_events

    conn = dbConn
    tenant = f"pr-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    from pathlib import Path

    rss = (Path(__file__).parent / "fixtures" / "press.xml").read_bytes()

    def llm_transport(request):
        resp = {
            "choices": [{"message": {"content": json.dumps({
                "company_name": "Acme Corp", "domain": "acme.com",
                "round_type": "series_a", "amount_usd": 12000000,
                "announced_on": "2026-11-06",
            })}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 100},
        }
        return 200, json.dumps(resp).encode()

    from substrate.sources.llm import LlmGateway

    llm = LlmGateway(
        base_url="https://llm.example/v1", model="extractor-1", api_key="env-only",
        run_budget_usd=5.0, price_per_mtok_in=1.0, price_per_mtok_out=1.0,
        transport=llm_transport, database_url=None,
    )

    class FakeFetcher:
        skipped_robots = 0
        def fetch(self, url, headers=None):
            return FetchResponse(url=url, status=200, body=rss)

    extracts, stats = extract_funding_events(
        FakeFetcher(), llm, "https://press.example/feed", persist_cache=False
    )
    assert stats.extracted == 2  # the two funding candidates extracted
    acme = [e for e in extracts if e.domain == "acme.com"][0]
    assert acme.source_url == "https://presswire.example/acme-series-a"  # the real article

    from substrate.sources.crawl import crawl_press_for_tenant

    class SameFetcher(FakeFetcher):
        pass

    report = crawl_press_for_tenant(conn, tenant_id, SameFetcher(), llm, "https://press.example/feed")
    assert report.stats.orgs_created == 1  # acme.com discovered
    assert report.stats.funding_events_written >= 1

    event = conn.execute(
        "SELECT url FROM funding_events WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    assert event[0].startswith("https://presswire.example/")  # real article, never LLM output

    tag = conn.execute(
        "SELECT value_norm FROM claims WHERE tenant_id = %s AND field = 'verification_status'",
        (tenant_id,),
    ).fetchone()
    assert tag is not None and tag[0] == "press_claimed"


def test_edgar_cik_anchoring_roundtrip(dbConn, monkeypatch):
    """watch_sources.sec_cik anchors Form D events deterministically."""
    monkeypatch.setenv("SUBSTRATE_SEC_CONTACT", "Ops <ops@example.com>")
    import json
    from datetime import date
    from pathlib import Path
    from uuid import uuid4

    from substrate.sources.crawl import crawl_edgar_for_tenant
    from substrate.sources.http import FetchResponse

    conn = dbConn
    tenant = f"ed-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)
    conn.execute("SELECT watch_upsert(%s, %s, %s, %s, %s, %s)",
                 (tenant_id, "acme.com", None, None, None, "0001234567"))
    conn.commit()

    efts_payload = json.loads((Path(__file__).parent / "fixtures" / "efts.json").read_text())
    efts = json.dumps(efts_payload).encode()

    class FakeFetcher:
        skipped_robots = 0
        def fetch(self, url, headers=None):
            assert "efts.sec.gov" in url
            assert "Ops" in (headers or {}).get("User-Agent", "")
            return FetchResponse(url=url, status=200, body=efts)

    report = crawl_edgar_for_tenant(
        conn, tenant_id, FakeFetcher(),  # type: ignore[arg-type]
        start=date(2026, 11, 1), end=date(2026, 11, 3),
    )
    assert report.truncated_events == 3  # fixture total 5, 2 events parsed
    assert report.skipped_unanchored == 1  # Beta Industries: no watch row, no slug match
    assert report.stats.funding_events_written == 1  # the CIK-matched Acme event

    ev = conn.execute(
        "SELECT url FROM funding_events WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    assert ev[0].startswith("https://www.sec.gov/Archives/edgar/data/")


def test_cross_tenant_and_ambiguous_anchors(dbConn):
    """Ownership FK rejects cross-tenant org refs; ambiguous anchors raise, never guess."""
    from uuid import uuid4

    import pytest

    from substrate.sources.writer import (
        AmbiguousAnchorError,
        find_org_by_domain,
        resolve_org_by_domain,
        resolve_person_by_email,
    )

    conn = dbConn
    tenant_a = f"xa-{uuid4().hex[:8]}"
    tenant_b = f"xb-{uuid4().hex[:8]}"
    ta = _fresh_tenant(conn, tenant_a)
    tb = _fresh_tenant(conn, tenant_b)
    org_a, _ = _org(conn, ta, "acme.com")
    conn.commit()  # pin org_a before the FK-failure rollback below

    # Cross-tenant org reference: the composite FK must reject it.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO job_postings "
            "(tenant_id, org_id, title_norm, source_type, url, retrieved_at) "
            "VALUES (%s, %s, 'engineer', 'greenhouse', 'https://x.example/1', now())",
            (tb, org_a),
        )
        conn.commit()
    conn.rollback()

    # Two orgs in one tenant claiming the same domain: ambiguous → raise (write path).
    conn.execute(
        "INSERT INTO organizations (tenant_id, name_canonical, domains) "
        "VALUES (%s, 'Acme Two', %s)",
        (ta, ["acme.com"]),
    )
    conn.commit()
    with pytest.raises(AmbiguousAnchorError, match="ER's decision"):
        resolve_org_by_domain(conn, ta, "acme.com")
    assert find_org_by_domain(conn, ta, "acme.com") is None  # dry-run: skip, never guess

    # Ambiguous person email: raise on the write path.
    conn.execute(
        "INSERT INTO persons (tenant_id, emails) VALUES (%s, %s), (%s, %s)",
        (ta, ["dup@example.com"], ta, ["dup@example.com"]),
    )  # two persons claiming one email: anchoring must refuse, not pick
    conn.commit()
    with pytest.raises(AmbiguousAnchorError, match="ER's decision"):
        resolve_person_by_email(conn, ta, "dup@example.com")


def test_two_watch_rows_one_org_merge(dbConn):
    """acme.com + acme.io → same CRM org: merged crawl must NOT flip-flop postings."""
    import json
    from uuid import uuid4

    from substrate.sources.crawl import crawl_careers_for_tenant
    from substrate.sources.http import FetchResponse

    conn = dbConn
    tenant = f"mg-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    # ONE CRM-imported org carrying BOTH domains — the collision this test covers
    # (separate unseen domains would just create separate orgs).
    conn.execute(
        "INSERT INTO organizations (tenant_id, name_canonical, domains) "
        "VALUES (%s, 'Acme Corp', %s)",
        (tenant_id, ["acme.com", "acme.io"]),
    )
    conn.commit()
    conn.execute("SELECT watch_upsert(%s, %s, %s, %s, %s, %s)",
                 (tenant_id, "acme.com", "acme", None, None, None))
    conn.execute("SELECT watch_upsert(%s, %s, %s, %s, %s, %s)",
                 (tenant_id, "acme.io", "acmeio", None, None, None))
    conn.commit()

    gh_engineer = json.dumps({"jobs": [{"id": 1, "title": "Engineer",
                                        "absolute_url": "https://boards.example/1",
                                        "departments": [], "offices": []}]}).encode()
    gh_seller = json.dumps({"jobs": [{"id": 2, "title": "Seller",
                                      "absolute_url": "https://boards.example/2",
                                      "departments": [], "offices": []}]}).encode()

    class FakeFetcher:
        skipped_robots = 0

        def fetch(self, url, headers=None):
            # Same platform (greenhouse), two boards, one shared org.
            assert "boards-api.greenhouse.io" in url
            if "/acme/" in url:
                return FetchResponse(url=url, status=200, body=gh_engineer)
            return FetchResponse(url=url, status=200, body=gh_seller)

    # Two runs must converge to the same stable state (no flip-flop).
    for _run in range(2):
        crawl_careers_for_tenant(conn, tenant_id, FakeFetcher())  # type: ignore[arg-type]
        conn.commit()

    open_rows = conn.execute(
        "SELECT title_norm FROM job_postings WHERE tenant_id = %s AND closed_at IS NULL "
        "ORDER BY title_norm",
        (tenant_id,),
    ).fetchall()
    assert [r[0] for r in open_rows] == ["engineer", "seller"]  # both alive, stable

    claim = conn.execute(
        "SELECT value_norm FROM claims WHERE tenant_id = %s AND field = 'hiring_activity' "
        "AND superseded_by IS NULL",
        (tenant_id,),
    ).fetchone()
    assert claim is not None and claim[0] == "open_postings:2"

    # Replay writes nothing new (replay-safety invariant).
    stable = crawl_careers_for_tenant(conn, tenant_id, FakeFetcher())  # type: ignore[arg-type]
    conn.commit()
    assert stable.stats.postings_written == 0
    assert stable.stats.claims_written == 0


def test_detector_delivery_roundtrip(dbConn):
    """Re-import with a changed title/org → detector emits job_change (idempotent)
    → delivery through a fake sink marks delivered_at."""
    from uuid import uuid4

    from substrate.signals.delivery import deliver_pending
    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"dt-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    # Import 1: Ann at Acme.
    rows1 = [{
        "contact_id": "003aa", "email": "ann@acme.com", "name_given": "Ann",
        "name_family": "Lee", "title": "VP Engineering", "org_name": "Acme",
    }]
    with conn.transaction():
        persist_contacts(conn, tenant_id, rows1, system="csv")

    # Detection before any move: silence. first_run=False: this test exercises
    # DELIVERY mechanics (pending events) — not first-run semantics.
    stats0 = detect_for_tenant(conn, tenant_id, first_run=False)
    assert stats0.events_written == 0

    # Import 2: same external id, moved to Beta as CTO.
    rows2 = [{
        "contact_id": "003aa", "email": "ann@acme.com", "name_given": "Ann",
        "name_family": "Lee", "title": "CTO", "org_name": "Beta",
    }]
    with conn.transaction():
        persist_contacts(conn, tenant_id, rows2, system="csv")

    # Detection (first_run=False): one job_change event.
    stats = detect_for_tenant(conn, tenant_id, first_run=False)
    assert stats.job_changes == 1
    assert stats.events_written == 1

    # Re-run: same pairs, idempotency key identical → nothing new.
    rerun = detect_for_tenant(conn, tenant_id, first_run=False)
    assert rerun.events_written == 0

    event = conn.execute(
        "SELECT event_type, old_state->>'org_name', new_state->>'org_name', delivered_at "
        "FROM events WHERE tenant_id = %s",
        (tenant_id,),
    ).fetchone()
    assert event[0] == "job_change"
    assert event[1] == "Acme" and event[2] == "Beta"
    assert event[3] is None  # not yet delivered

    # Delivery through a recording sink marks delivered_at.
    sink = RecordingSink()
    delivery = deliver_pending(conn, tenant_id, sink)
    assert delivery.delivered == 1
    assert len(sink.payloads) == 1
    assert "Acme" in sink.payloads[0]["text"] and "Beta" in sink.payloads[0]["text"]

    # Committed-state proof on a SECOND connection: a savepoint-only write would
    # be invisible here (gate round-3: delivered_at must survive rollback/close).
    import os

    import psycopg

    conn2 = psycopg.connect(os.environ["SUBSTRATE_TEST_DATABASE_URL"])
    delivered = conn2.execute(
        "SELECT delivered_at FROM events WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    conn2.close()
    assert delivered[0] is not None, "delivered_at was not committed"


def test_promotion_signal_roundtrip(dbConn):
    """Same org, seniority up → promotion event, not job_change."""
    from uuid import uuid4

    from substrate.signals.delivery import deliver_pending
    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"pr-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    with conn.transaction():
        persist_contacts(conn, tenant_id, [{
            "contact_id": "003pp", "email": "pat@acme.com", "name_given": "Pat",
            "name_family": "Ng", "title": "Engineer", "org_name": "Acme",
        }], system="csv")
    with conn.transaction():
        persist_contacts(conn, tenant_id, [{
            "contact_id": "003pp", "email": "pat@acme.com", "name_given": "Pat",
            "name_family": "Ng", "title": "Director of Engineering", "org_name": "Acme",
        }], system="csv")

    stats = detect_for_tenant(conn, tenant_id, first_run=False)
    assert stats.promotions == 1
    assert stats.job_changes == 0

    sink = RecordingSink()
    delivery = deliver_pending(conn, tenant_id, sink)
    assert delivery.delivered == 1
    assert "promoted" in sink.payloads[0]["text"]


def test_no_sink_reports_skipped(dbConn):
    from uuid import uuid4

    from substrate.signals.delivery import deliver_pending
    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"ns-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "VP", "org_name": "Acme"},
        ], system="csv")
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "CTO", "org_name": "Beta"},
        ], system="csv")
    detect_for_tenant(conn, tenant_id, first_run=False)

    delivery = deliver_pending(conn, tenant_id, None)  # no sink configured
    assert delivery.skipped_not_configured == 1
    assert delivery.delivered == 0


def test_canary_replay_rolls_back(dbConn):
    """Canary replay owns a dedicated rolled-back tenant: recall measured, nothing persists."""
    from pathlib import Path

    from substrate.signals.canary import replay

    conn = dbConn
    before_tenants = conn.execute("SELECT count(*) FROM tenants").fetchone()[0]
    before_persons = conn.execute("SELECT count(*) FROM persons").fetchone()[0]

    fixture = Path(__file__).parent / "fixtures" / "canary_moves.json"
    report = replay(conn, fixture)  # owns + rolls back its dedicated tenant
    conn.commit()  # settle after the rollback

    assert report["canaries"] == 3
    assert report["detection_recall"] == 1.0
    assert report["missed"] == []
    assert report["pairs_diffed"] == 3  # scoped to the canary tenant only

    # Rollback proof (non-trivial): canary persons/events gone, tenant count unchanged.
    assert conn.execute("SELECT count(*) FROM tenants").fetchone()[0] == before_tenants
    assert conn.execute("SELECT count(*) FROM persons").fetchone()[0] == before_persons
    assert conn.execute(
        "SELECT count(*) FROM tenants WHERE name LIKE 'canary-replay-%'"
    ).fetchone()[0] == 0


def test_detector_multi_version_history(dbConn):
    """A→B→C history with detection after every import (continuous model):
    job_change fires on the move, the later retitle is a promotion — never a
    second job_change, never a missed move (gate rounds 1–2, both models)."""
    from uuid import uuid4

    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"mv-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    history = [
        {"contact_id": "003mm", "email": "mia@alpha.com", "name_given": "Mia",
         "name_family": "Chen", "title": "Engineer", "org_name": "Alpha"},
        {"contact_id": "003mm", "email": "mia@alpha.com", "name_given": "Mia",
         "name_family": "Chen", "title": "Platform Engineer", "org_name": "Beta"},  # move
        {"contact_id": "003mm", "email": "mia@alpha.com", "name_given": "Mia",
         "name_family": "Chen", "title": "Senior Platform Engineer",
         "org_name": "Beta"},  # promotion
    ]

    # Continuous detection: one run after EACH import — exactly how production runs.
    # Round-1's latest-pair-only fix swapped false alerts for silent misses; the
    # consecutive-pair model must catch every step, never double-report any.
    expected = [0, 1, 1]  # cumulative job_changes after each run
    for i, rows in enumerate(history):
        with conn.transaction():
            persist_contacts(conn, tenant_id, [rows], system="csv")
        detect_for_tenant(conn, tenant_id)
        cumulative = conn.execute(
            "SELECT count(*) FROM events WHERE tenant_id = %s "
            "AND event_type = 'job_change'",
            (tenant_id,),
        ).fetchone()[0]
        assert cumulative == expected[i], f"run {i+1}: {cumulative} != {expected[i]}"

    # The retitle after the move became a promotion (seniority up at same org),
    # never a second job_change.
    kinds = [r[0] for r in conn.execute(
        "SELECT event_type FROM events WHERE tenant_id = %s ORDER BY detected_at", (tenant_id,)
    ).fetchall()]
    assert kinds == ["job_change", "promotion"]


def test_at_least_once_failure_keeps_event_pending(dbConn):
    """Sink failure → event stays pending (at-least-once), retried on next run."""
    from uuid import uuid4

    from substrate.signals.delivery import deliver_pending
    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"fl-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "VP", "org_name": "Acme"},
        ], system="csv")
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "CTO", "org_name": "Beta"},
        ], system="csv")
    detect_for_tenant(conn, tenant_id, first_run=False)

    class FailingSink:
        configured = True

        def deliver(self, payload: dict) -> bool:
            return False  # webhook down

    # False-return branch: webhook down — event stays pending, retried next run.
    delivery = deliver_pending(conn, tenant_id, FailingSink())  # type: ignore[arg-type]
    assert delivery.failed == 1 and delivery.delivered == 0
    assert "sink returned failure" in delivery.errors[0]
    pending = conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    assert pending == 1

    # Raising branch: the report carries the exception TYPE, never the message
    # (urllib errors can embed the webhook URL — a secret).

    class RaisingSink:
        configured = True

        def deliver(self, payload: dict) -> bool:
            raise RuntimeError("POST https://hooks.example/secret-token failed")

    delivery2 = deliver_pending(conn, tenant_id, RaisingSink())  # type: ignore[arg-type]
    assert delivery2.failed == 1
    assert all(err.endswith(": RuntimeError") for err in delivery2.errors)
    assert all("hooks.example" not in err for err in delivery2.errors)

    pending = conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    assert pending == 1  # still pending — retried on the next run

    # Recovery run succeeds.
    class WorkingSink:
        configured = True

        def deliver(self, payload: dict) -> bool:
            return True

    delivery2 = deliver_pending(conn, tenant_id, WorkingSink())  # type: ignore[arg-type]
    assert delivery2.delivered == 1


def test_first_run_records_without_alerting(dbConn):
    """--first-run semantics: historical moves are RECORDED with delivered_at set —
    no Slack flood from a tenant with re-import history."""
    from uuid import uuid4

    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"fr-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    # Two historical moves exist before the first detection run.
    for rows in (
        [{"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
          "title": "Engineer", "org_name": "Alpha"}],
        [{"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
          "title": "Senior Engineer", "org_name": "Beta"}],
        [{"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
          "title": "CTO", "org_name": "Gamma"}],
    ):
        with conn.transaction():
            persist_contacts(conn, tenant_id, rows, system="csv")

    # Forced first run (explicit --first-run → first_run=True): same suppression,
    # even if a prior detect_runs row existed.
    stats = detect_for_tenant(conn, tenant_id, first_run=True)
    assert stats.events_written == 2  # both moves recorded

    delivered = conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NOT NULL",
        (tenant_id,),
    ).fetchone()[0]
    assert delivered == 2  # recorded AND marked delivered — no Slack flood

    pending = conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    assert pending == 0


def test_auto_first_run_real_move_still_alerts(dbConn):
    """The gate r14 scenario: backlog suppressed on the first run, but the
    tenant's first GENUINE move (a later run) alerts — never silently marked."""
    from uuid import uuid4

    from substrate.signals.detector import detect_for_tenant
    from substrate.store import persist_contacts

    conn = dbConn
    tenant = f"af-{uuid4().hex[:8]}"
    tenant_id = _fresh_tenant(conn, tenant)

    # Backlog: two historical moves before detection ever runs.
    for rows in (
        [{"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
          "title": "Engineer", "org_name": "Alpha"}],
        [{"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
          "title": "Senior Engineer", "org_name": "Beta"}],
    ):
        with conn.transaction():
            persist_contacts(conn, tenant_id, rows, system="csv")

    # Run 1 (auto first run, detector-level): backlog recorded as delivered.
    stats1 = detect_for_tenant(conn, tenant_id)
    assert stats1.events_written >= 1
    assert conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
        (tenant_id,),
    ).fetchone()[0] == 0

    # A GENUINE move happens now (import 3), then run 2 — the move ALERTS.
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "CTO", "org_name": "Gamma"},
        ], system="csv")
    stats2 = detect_for_tenant(conn, tenant_id)
    assert stats2.events_written >= 1

    pending = conn.execute(
        "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    assert pending >= 1  # the genuine move is PENDING — it will alert

    # Run marker recorded: the auto decision is anchored to tenant history, not
    # an inference from zero events (the r14 flaw this test guards).
    marker = conn.execute(
        "SELECT 1 FROM detect_runs WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    assert marker is not None

    def _pending() -> int:
        return conn.execute(
            "SELECT count(*) FROM events WHERE tenant_id = %s AND delivered_at IS NULL",
            (tenant_id,),
        ).fetchone()[0]

    # Forced contract: first_run=True suppresses EVEN with prior runs (r17) —
    # the NEW move from this run records pre-delivered. Assertions are run-scoped
    # (delta), so older pending events can't make them pass trivially.
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "SVP Product", "org_name": "Omega"},
        ], system="csv")
    before = _pending()
    forced = detect_for_tenant(conn, tenant_id, first_run=True)
    assert forced.events_written >= 1  # the new move recorded
    assert _pending() == before        # run-scoped: nothing NEW left pending

    # first_run=False forces ALERTING: the same move re-detected... uses a new
    # position, so instead assert False-mode leaves its events pending for
    # delivery on a NEW move.
    with conn.transaction():
        persist_contacts(conn, tenant_id, [
            {"contact_id": "1", "email": "a@x.com", "name_given": "A", "name_family": "B",
             "title": "Chief Product Officer", "org_name": "Omega"},
        ], system="csv")
    before = _pending()
    alerted = detect_for_tenant(conn, tenant_id, first_run=False)
    assert alerted.events_written >= 1  # the new move detected
    assert _pending() == before + 1     # explicit alerting: stays pending for delivery
