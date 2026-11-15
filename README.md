# Substrate

**The living knowledge graph for go-to-market.** Salesforce is the system of record. Clay is the system of action. Substrate is the system of truth — every company, person, job, and relationship edge, resolved with provenance and streamed as it changes.

> Venture monorepo: planning docs + core services. Postgres-only topology per PLAN §2 — no graph DB in v1.

## Documents

| Doc | What it is |
|---|---|
| [PRD — v0.2 (2026-11-12)](docs/PRD-living-gtm-graph-2026-11-12.md) | Master product requirements: thesis, market evidence, wedge (Champion Graph), ER architecture, competitive landscape, pricing, metrics, decisions |
| [PLAN — M0–M2 execution (2026-11-12)](docs/PLAN-substrate-m0-m2-execution-2026-11-12.md) | 9-week build spec for the Resolve layer: scope lock, topology, DDL intent, ER engine, sources, week-by-week gates, burn |
| [KIT — design-partner outreach (2026-11-12)](docs/KIT-substrate-partner-outreach-2026-11-12.md) | ICP, target-list construction, outreach sequences with copy, Audit landing copy, partner term sheet, onboarding + M0 kickoff checklists |

## Status

- **M0 kickoff:** 2026-12-01 · gates land ~Feb / May / Sep / Dec 2027 (calendar slips before gates do)
- **Current lane:** W3–4 — ER v0 (deterministic, precision-first), golden-set sampler/harness, Graph Audit v0 (PLAN §7)
- **Current gate:** M2 — resolution ≥80% on 3 design-partner CRMs, merge precision ≥99.5%, zero privacy incidents
- **Next artifact:** ~~design-partner outreach kit~~ shipped · next: code (M0–M2 build per PLAN §7), pitch deck deferred to M2 evidence

## Dev setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check src tests && .venv/bin/mypy src && .venv/bin/pytest -q
.venv/bin/substrate import-csv --tenant demo --contacts-file export.csv --report report.json --dry-run
```

Layout: `src/substrate/` core services (config · db + migration runner · reconciliation · importers · store) · `db/migrations/` numbered SQL · `terraform/` infra (applied from the remote plane only) · `docs/` PRD / PLAN / KIT.

## Working agreements

- Milestones are gated by measured acceptance, never calendar (see PRD §12).
- Identity decisions are deterministic/learned ER — LLMs extract, never decide identity.
- Raw plan files mirror to the rig workspace; this repo is canonical for the venture.
