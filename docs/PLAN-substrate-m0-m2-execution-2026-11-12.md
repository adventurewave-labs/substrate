# PLAN: Substrate M0–M2 execution spec (Resolve layer)

**Date:** 2026-11-12 · **Status:** draft for review · **Parent:** [PRD-living-gtm-graph-2026-11-12.md](PRD-living-gtm-graph-2026-11-12.md) (§12 gates)
**Scope window:** M0 = 2026-12-01 → M2 gate ≈ 2027-02-09 (9 weeks)
**Ship target:** F1 (CRM import & resolution) + F5 (Graph Audit, report-only v0) + F2-partial (`job_change` detection + Slack delivery + precision instrumentation), at M2-gate quality on 3+ design-partner CRMs.

---

## 1. Scope lock

**In:**
- SFDC + HubSpot read-only connect, CSV import
- ER v0 → v1 (blocking → pairwise scorer → constrained clustering) with golden-set eval
- Claims store + provenance on every attribute
- Crawlers: careers pages, SEC EDGAR Form D, funding press
- Licensed feed adapters: Coresignal + PDL (two vendors max in this window)
- `job_change` detector + Slack delivery + CRM contact-field writeback
- Graph Audit report generator (resolution/dup/stale report; movement scan added at W8 when the graph has mass)
- Precision instrumentation + canary replay from W7 (not W9 — measurement ships with the feature)

**Out (explicitly, per PRD §5):** API surface, Clay block, reverse ETL, MCP, promotions signal, destination enrichment, warm-path edges, org charts, talent nouns, any UI beyond internal console + Audit report.

**Build-vs-buy rulings:**
| Decision | Ruling | Why |
|---|---|---|
| Graph DB | **No.** Postgres + recursive CTEs | 10M nodes is nothing; subtraction over addition (Law 8); graph DB is an M15+ migration question, not an M1 one |
| CRM connectors | Buy the SDKs (`simple-salesforce`, HubSpot official), build thin adapters | Never hand-roll OAuth |
| Pipeline orchestration | **Dagster OSS** | Asset lineage + backfills are exactly the ER retraining workflow; 2-person team can still operate it |
| ER scorer | LightGBM pairwise + hard constraints; embeddings as features only | Auditable, retrainable, cheap — no LLM in the identity path |
| LLM extraction | Provider-agnostic gateway, structured output, aggressive caching | Extraction only; never identity (PRD anti-drift rule) |
| IaC | Terraform from day 1, staging = prod-shaped | Data company = infra hygiene is the product |

> **Deviation (2026-11-15, W5–6 lane):** Dagster does not yet wheel for the dev
> venv's Python 3.14, so the crawl pipeline ships as plain deterministic functions
> with checkpoint reuse (`import_checkpoints`) and an injectable HTTP transport.
> The functions wrap into Dagster assets unchanged once the venv pins to a
> supported Python (tracked as W9 housekeeping). No behavioral change to the
> W5–6 acceptance criteria.

---

## 2. Architecture (v1 topology)

```
sources                      extract                      resolve                    deliver
─────────                    ───────                      ───────                    ───────
SFDC/HubSpot (read) ─┐
CSV upload ──────────┤
careers crawl ───────┼──▶ Dagster assets ──▶ claims store ──▶ ER service ──▶ graph (Postgres)
EDGAR Form D ────────┤    (LLM extract,        (claims +          (block →       │
funding press ───────┤     schema-                 provenance)      score →        ├─▶ Slack alerts
Coresignal feed ─────┤     constrained)                             cluster)      ├─▶ CRM writeback
PDL feed ────────────┘                                                           └─▶ Audit reports
                                                          │
                                                    review queue (internal UI)
                                                          │
                                                    eval harness (golden set · canary · precision dashboard)
```

- **One managed Postgres** (partitioned: `entities`, `claims`, `positions` (bitemporal), `edges`, `events`, `golden_set`, `review_queue`). Raw claim payloads to object storage, hashed pointers in-row.
- **Workers:** containerized Python on one cloud (GCP default; AWS acceptable), Cloud Run/ECS for crawls + ER batches, SQS/PubSub for event delivery.
- **Secrets:** cloud KMS; customer CRM creds per-tenant, read-only scopes only.

---

## 3. Data model (v1 DDL intent — bitemporal from day 1)

```sql
-- every attribute assertion, immutable
claims(id, entity_id, field, value_norm, value_raw_ref,
       source_type, source_id, url, retrieved_at, extractor_version,
       confidence, superseded_by)

-- bitemporal employment
positions(id, person_id, org_id, title_norm, seniority,
          valid_start, valid_end,            -- when true in the world
          txn_from, txn_to)                  -- when we believed it

-- identity decisions, replayable
merge_decisions(id, cluster_a, cluster_b, score, decision,  -- auto_merge|review|reject
                featureset_version, decided_at, decided_by)

-- observability output
events(id, event_type, entity_id, old_state, new_state,
       confidence, provenance_refs[], detected_at, delivered_at, customer_verdict)
```

Rules: claims are append-only; corrections are new claims with `superseded_by`; `merge_decisions` makes every identity auditable ("why are these one person?" has an answer); erasure = tombstone cascade walking `merge_decisions` + `edges`.

---

## 4. ER engine (v0 → v1)

**v0 (W3–4) — deterministic:** email/domain canonicalization, exact-name + employer blocking, phonetic keys. Enough to produce first Audit reports and bootstrap labels.

**v1 (W7–8) — learned:**
- Features: name sim (Levenshtein + embedding cosine), email/domain evidence, title-history consistency, employer-overlap, temporal-consistency flags, source-agreement count.
- LightGBM pairwise → constrained clustering (must-not-link: simultaneous distinct employers, divergent public identities).
- Bands: ≥0.995 auto-merge · 0.90–0.995 internal review queue · <0.90 no merge. Review queue is *ours*, not the customer's, in this window.

**Golden set bootstrap (the founder-craft piece):**
1. From each of 3 design-partner CRM dumps: stratified sample of 500 pairs — exact-email dupes / fuzzy name + same org / fuzzy name + diff org / hard negatives (common names, real distinct people).
2. Hand-label (~2 founder-days, once). Labels are contracts: disputes get adjudicated and the label wins.
3. Merge precision gate measured on this set at every scorer change; refresh +200 pairs monthly from review-queue traffic.
4. Blocking recall is measured separately (golden pairs that never meet in a block = silent misses): **blocking recall ≥99%** or the blocking keys change — no exceptions.

---

## 5. Source plan (M0–M2)

| Source | Type | Est. cost | Notes |
|---|---|---|---|
| Customer CRM | first-party | $0 | anchor entity set; read-only OAuth |
| Coresignal (company + employee datasets) | licensed | ~$1.5K/mo | entry dataset tier |
| PDL (person + company API) | licensed | ~$0.5K/mo | redundancy for Coresignal; never single-vendor |
| SEC EDGAR Form D / filings | public | $0 | US funding events, exec changes; free + citable |
| Careers pages (Greenhouse/Lever/Ashby public endpoints) | public crawl | infra only | robots/ToS-respecting, rate-limited; job-board vendor decision deferred to M3 |
| Funding press (TechCrunch/PR blogs RSS) | public | $0 | secondary corroboration for Form D |

Licensing line: **~$2K/mo**, two vendors, cancellation rights confirmed at signature (PRD §10.2 COGS floor).

---

## 6. Graph Audit (F5) — MVP behavior

- W4 ship: CSV or connect → **resolution report** (% resolved, dup %, stale-title %) as a branded HTML/PDF. Honest bounds: movement counts appear only where the graph covers; uncovered contacts say "unresolved," never guessed.
- W8 ship: **movement scan** — "N champions moved in 90 days" — gated on graph mass; every listed move click-through to provenance.
- Gate: work email + read-only connect. This artifact is the design-partner sales weapon and the M2 evidence pack's cover page.

---

## 7. Week-by-week (9 weeks)

| Week | Deliverable | Acceptance |
|---|---|---|
| W1–2 | Terraform + Postgres schema + SFDC/HubSpot connect + CSV import | import 3 partner CRMs; row-level reconciliation report |
| W3–4 | ER v0 + golden set v0 labeled + Audit resolution report | first partner Audits delivered; golden set locked (500 pairs) |
| W5–6 | Crawlers (careers, EDGAR, press) + LLM extraction + claims store + 2 feed adapters | 10K claims/day steady-state; provenance on 100% of claims |
| W7–8 | ER v1 scorer + clustering + position snapshots + `job_change` detector + Slack + writeback + canary replay | merge precision ≥99.5% on golden set; first real alerts to partners |
| W9 | M2 gate audit + evidence pack | PRD §12 gate: resolution ≥80% on 3 CRMs, zero privacy incidents, canary TTR baseline recorded |

**Owners:** tech founder — schema, ER, pipelines · GTM lead (co-founder or hire #2) — partner agreements, Audit delivery, verdict collection (every alert gets a 👍/👎 in Slack; verdicts feed the precision dashboard).

---

## 8. Burn (M0–M2, pre-revenue)

| Line | Est. |
|---|---|
| Data licensing (2 vendors × ~2.5 mo) | ~$5K |
| Infra (compute + storage + egress) | ~$3K |
| Privacy counsel retainer (starts W1, not W9) | ~$5K |
| Tooling/misc | ~$2K |
| **Total window burn** | **~$15K** (founder time excluded) |

---

## 9. Risks in this window

| # | Risk | Mitigation |
|---|---|---|
| 1 | Partner agreements slip past W2 | GTM lead's only W1–2 metric is signed partners; PRD §15 targeting list is the pipeline; Audit-on-CSV unblocks partners who can't do OAuth fast |
| 2 | Golden set too small to trust the gate at W9 | hard negatives are 40% of the sample; W7 dry-run gate on v0 data catches scorer inadequacy with 2 weeks to fix |
| 3 | LLM extraction cost blowup | per-claim budget ceiling + cache-first; extraction is ≤10% of pipeline cost by design |
| 4 | Crawl ToS friction on careers pages | public JSON endpoints + rate limits + robots compliance; vendor fallback decision pre-approved for M3 |
| 5 | Scope creep into destination intelligence (F3) early | it's M3 per PRD; alerts ship with org name + title only until then |

---

## 10. M2 exit → what "next" means after this

- **Evidence pack assembled at W9:** precision dashboard, canary TTR, 3-partner resolution stats, first alert→meeting stories → this opens the seed conversations (PRD §10.3).
- **Next artifacts after this spec:** (1) design-partner outreach kit (ICP one-pager, Audit-first sequence, agreement template) — W1 dependency, so it ships *this week* in draft form; (2) pitch deck — drafted at M2, not before.
