# PRD: Substrate (working title) — the living knowledge graph for go-to-market

**Date:** 2026-11-12 · **Status:** v0.2 — open values committed (see §15) · **Author:** session PRD per mp
**One-liner:** Salesforce is the system of record. Clay is the system of action. Nobody owns the system of truth. Substrate is the maintained entity graph for GTM — every company, person, job, and relationship edge, resolved with provenance, and streamed to wherever revenue teams and their agents already work.

---

## 0. Document card

| | |
|---|---|
| **Product** | A maintained, bitemporal knowledge graph of B2B companies, people, and change-signals, sold as (1) a champion-tracking wedge product and (2) a graph/change-stream API + warehouse-native platform |
| **Founder profile this is designed for** | Prior founding experience · pre-LLM ML / knowledge-graph / semantic-search background · shipped CRM-style intelligence products (RevOps or recruiting) |
| **Wedge** | Champion Graph: "every champion you ever lost track of, caught the week they move, with the warm path and a drafted intro" |
| **Why this founder** | Entity resolution and retrieval evaluation are pre-LLM crafts; the LLM-native field is weak exactly there |
| **Wedge WTP evidence** | UserGems ~$40K+/yr, Champify $15–30K/yr, ZoomInfo Tracker + Agent Teams — the niche is paid-for and incumbents are validating it from a decaying base |
| **v1 headcount assumption** | 2 founders + hire #1 (data/ER engineer, ~M1) + hire #2 (founding AE, ~M4) + data-ops contractor; infra on managed services |
| **12-month target** | 10 design partners → ~$150K ARR wedge revenue, platform beta, SOC 2 Type I, precision published |
| **Seed ask** | $3.5M on post-M2-gate evidence; 24-month runway; targets in §10.3 |

---

## 1. The founder-fit thesis (why this profile builds this product)

The 2025–26 GTM market produced three facts at once:

1. **The workflow layer exploded** — Clay went $1M → $100M ARR in ~42 months ($7.1B valuation, Sept 2026). Every Clay workflow is duct tape over vendor APIs ("waterfall enrichment") because *nobody owns the truth layer underneath*.
2. **The data incumbents decayed** — ZoomInfo ~1% YoY growth, 89% net revenue retention, stale-contact complaints; Apollo wins on price with 15–30% bounce rates. Buyers are shopping for accuracy and finding none.
3. **The agent layer arrived and hit a wall** — Agentforce, Breeze, ZoomInfo Agent Teams (DoubleO.AI), Clay agents. Agents are bottlenecked on identity and freshness, not model quality. An agent that can't tell which "J. Smith" it's emailing is a liability, and the AI-SDR category proved it (70–80% churn, inflated ARR claims, deliverability damage).

All three facts point at the same missing layer: **a resolved, fresh, provenance-carrying graph with change streams.** That layer is not a model problem — it's a systems problem built from pre-LLM crafts:

| Founder trait | Product component it owns | Why LLM-native teams can't fake it |
|---|---|---|
| Pre-LLM ML (record linkage, dedup) | The ER engine: blocking, pairwise scoring, constrained clustering, precision/recall evals | "Ask GPT if these are the same company" costs cents per pair, drifts run-to-run, and can't do transitive closure or must-not-link constraints at 10M+ nodes |
| Knowledge graphs | Bitemporal entity model, relationship edges, provenance chains, erasure cascades | Ontology design and temporal identity are architecture, not prompting |
| Semantic search (pre-LLM) | Signal extraction from firehoses: hybrid retrieval (BM25+dense), reranking, recall@k harnesses over job boards, filings, press, communities | Retrieval evaluation discipline — knowing your recall is 61% and fixing the blocking key — is a learned craft |
| CRM-intelligence product history (RevOps/recruiting) | The workflow surfaces: CRM writeback hygiene, SFDC object models and API limits, Slack-native UX, what a pipeline review actually looks like | The graveyard of GTM tools is full of great data with terrible CRM integration trust |
| Prior founding | Wedge choice with an existing budget line; infrastructure optionality; speed over ceremony | — |

**The strategic bet:** agents commoditize; *memory* is the moat. Build the memory.

---

## 2. Market evidence (researched 2026-11-12)

- **Clay**: $100M ARR Dec 2025, ~17K customers, Series D $115M at $7.1B (Sept 2026), tracking toward ~$200M ARR. Proof of workflow appetite and of a partner ecosystem that *needs* a better data layer.
- **ZoomInfo**: quarterly revenue ~$310M, +1.2% YoY; NRR 89%; goodwill impairment; recurring G2/community complaints about stale contacts and wrong direct dials. Response: AI-repositioning (Copilot, MCP server, **Agent Teams via the DoubleO.AI acquisition, Oct 2026**) — incumbents are bolting agents onto a stale graph, which validates the wedge and exposes their weakness simultaneously.
- **Apollo**: ~$194M ARR end-2025 → ~$265M by Sept 2026 (Sacra est.); 15–30% email bounce rates reported by independent reviews; LinkedIn company page delisted early 2025 over policy violations. Price wins, truth loses.
- **AI SDR backlash**: 11x claimed $14M ARR vs ~$3M real (TechCrunch, Mar 2025) with 70–80% customer loss reported; category post-mortems ("deathtocoldemails") argue autonomy was oversold; 40–60% of AI-SDR pilots shut within 90 days per Alleyoop. Buyers now demand *verifiable, deterministic* signals over agent autonomy — trust became the product surface.
- **Signal-based selling is mainstream**: Apollo publishes a GTM Engineering program around it; "GTM engineering" search volume surpassed "RevOps"; ~3,000 open GTME roles by early 2026 (Onfire). A new buyer persona with its own budget exists and assembles stacks themselves — they hate black boxes and love published precision.
- **Champion tracking WTP**: UserGems ~$40K+/yr plus implementation; Champify $15–30K SMB tier; practitioners actively switch between them; ZoomInfo shipped Tracker natively (2022) and agent-ized it (2026). Small, proven, and *not won*.
- **Raw people-data is a commodity**: PDL ~$98–600/mo self-serve; Coresignal $49/mo API entry, $1–1.5K/mo datasets. The moat is not data access — it's resolution quality, freshness, provenance, and workflow-native delivery.
- **The slot is empty**: Graphify Labs (YC S26) is a *horizontal* KG engine; Graphiq is content-stage; Centralize is deal-intelligence; Tamr is enterprise MDM (validates the tech, wrong motion). Nobody owns the GTM-specific resolved graph with change streams.

**Timing thesis in one line:** this is the moment *after* the workflow layer won and *before* the agent layer matured — the only window in which a data-infrastructure layer gets adopted as a peer instead of absorbed.

---

## 3. Problem (the user's day, stated as evidence)

A RevOps lead at a 200-person B2B SaaS company, on a Tuesday:

1. **Their CRM is a graveyard of identity.** 40K contacts, ~30% duplicates, stale titles, "J. Smith" appearing 6 ways. Every enrichment run re-breaks merges someone fixed by hand.
2. **Their best asset — closed-lost history — is unreachable.** The champions who evaluated and loved the product two years ago now run engineering at companies currently hiring. Nobody is watching them, because no point tool resolves identity well enough to trust the alert.
3. **Every signal tool they bought lied at least once.** One false "your champion moved!" alert per month is enough to mute the channel forever. Vendors don't publish precision because they can't measure it.
4. **Their new GTM engineer is drowning in duct tape.** Clay chains five enrichment APIs per row with no confidence scores, no provenance, no reconciliation. The stack "works" and nobody trusts it.
5. **Their AI copilot hallucinates accounts.** Agentforce/Breeze answer questions over the CRM — which is wrong — so the agent is confidently wrong at scale.

The unifying root cause: **no maintained identity layer**. Every downstream product (signals, agents, enrichment, forecasting) inherits the error.

---

## 4. Product thesis & architecture

**Three layers, shipped as one system:**

```
┌────────────────────────────────────────────────────────────┐
│  ACT      Slack digests · CRM writeback · webhooks ·        │
│           Clay block · reverse-ETL · MCP server · API       │
├────────────────────────────────────────────────────────────┤
│  OBSERVE  Change streams: job changes, promotions, funding, │
│           hiring-at-destination, tech adoption, news        │
│           (typed SignalEvents with confidence + provenance) │
├────────────────────────────────────────────────────────────┤
│  RESOLVE  Entity resolution engine → bitemporal graph:      │
│           Organization · Person · Position · FundingEvent · │
│           JobPosting · RelationshipEdge · Claim(provenance) │
└────────────────────────────────────────────────────────────┘
```

**Positioning line for the market:** "The system of truth under your system of action."

**Architectural stance (the anti-drift rule):** LLMs do *extraction and normalization* (titles → role taxonomy, org-name variants → canonical, unstructured → claims). LLMs never decide *identity*. Identity is deterministic/learned ER, because identity must be consistent, auditable, and cheap at scale. This single rule is why a pre-LLM-ML founder wins this product.

**Bitemporality is the trust feature:** every Position carries *valid time* (when the employment was actually true) and *transaction time* (when we learned it). Customers can ask "what did Substrate believe on March 1?" — no data vendor offers this, and it converts skeptics because audits become possible.

---

## 5. Non-goals (v1)

- **No email sending, no sequences, no dialers.** We feed the systems that send; we are not another outreach tool. (Category fatigue works against senders.)
- **No LinkedIn scraping or automation.** Legal/ToS risk is existential for a data company; the source mix below is deliberate.
- **No org charts / buying-committee graphs in v1.** The only fresh source of reporting lines is LinkedIn — legally fraught. Org inference waits for first-party graph mass (customer CRM edges + email metadata with consent). P2.
- **No B2C personal data, ever.** B2B professional contacts only. This is a hard product line and a marketing line.
- **No generic MDM / "data quality suite."** We are GTM-shaped: the ontology, the signals, and the workflows are revenue-specific.
- **No horizontal graph engine.** Graphify-style platform sales is a different company; our engine stays internal.

---

## 6. The wedge: Champion Graph (v1 scope)

**Job to be done:** "When someone who ever touched my pipeline lands somewhere new, put it in front of the right rep within days — with a warm path I trust and an intro I can send."

### F1 — CRM import & resolution — P0, milestone M1
Read-only connect (SFDC, HubSpot) or CSV export import. Resolve every contact/account into graph nodes; suppress duplicates; backfill position history from whatever the CRM carries. Output: a Graph Audit report (see F5) within 48 hours of connect.
*Acceptance:* ≥85% of contacts resolved to live nodes on design-partner CRMs; ≥30% duplicate suppression; audit-sample merge precision ≥99.5% (n≥500).

### F2 — Change detection: job changes & promotions — P0, milestone M1–M2
Watch resolved persons against the source mix (§7). Typed events: `job_change`, `promotion`. Every event ships with: old/new state, confidence, and click-through provenance (≥2 independent sources, or 1 primary + corroboration flag).
*Acceptance:* event precision ≥98% (customer-validated, 90-day rolling); median time-to-reported ≤7 days on canary accounts; zero silent merges (every event traceable to its cluster decision).

### F3 — Destination intelligence — P0, milestone M3
For each event, enrich the destination org: funding event, hiring activity for the champion's function, headcount trajectory. Rank events by "destination is in-market" — a champion who moved to a company actively hiring their function is the highest-value signal in B2B.
*Acceptance:* destination signals attached to ≥90% of job_change events; in-market ranking demonstrated to lift meetings-per-alert in design-partner retros.

### F4 — Warm path & delivery — P0, milestone M3–M4
For each event: the owning rep (CRM owner, fallback round-robin), the best relationship edge we can honestly claim (shared employer history in CRM, champion's new colleagues who are our customers, mutual CRM co-travel on past opportunities), and a drafted intro grounded only in verifiable context. Delivery: Slack (primary), CRM task + contact upsert (writeback with source tag), webhook.
*Acceptance:* false warm-path claims <2% (edges carry evidence type); writeback failure rate <0.1%; reps rate alerts useful ≥70%.

### F5 — Graph Audit (free self-qualifying scan) — P0, milestone M1 (growth engine)
Free: point Substrate at your CRM read-only → get a report: resolution rate, duplicate %, stale-title %, "N champions moved in the last 90 days, M landed at companies hiring your function, K have a warm path through your customers." Gated by work email + read-only connect. This is the PLG motion, the sales-qualification motion, and the graph-seeding motion in one artifact.

### F6 — Signals API + Clay block + reverse ETL — P1, milestone M4–M6
The graph exits our UI: REST + webhook API for events/entities; a first-class Clay column/block; Hightouch/Census targets; Snowflake share. Monetization switches from seats to consumption as this ramps.
*Acceptance:* ≥2 external integrations live (Clay block + one reverse-ETL target); p95 API latency <300ms for entity reads; stream fan-out ≤15 min from detection.

### F7 — MCP server ("give your agent a memory") — P1, milestone M6–M8
Expose entity-lookup, relationship-query, and event-subscribe as MCP tools. Pitch: every GTM agent (Agentforce, Clay agents, custom) is only as good as its identity layer; Substrate is the identity layer with provenance. Beta with 5 agent-building teams.
*Acceptance:* 5 active MCP consumers; agents' identity error rate measurably lower with Substrate tools vs. free-text lookup (publish the delta).

---

## 7. Data architecture & the ER engine (founder-craft section)

### 7.1 Entity model (v1)
- `Organization`: canonical org, domains[], HQ, size band, industry, funding events (temporal).
- `Person`: canonical person; no consumer attributes; professional only.
- `Position`: (person, org, title_normalized, seniority, start, end?) — **bitemporal**: valid_time + transaction_time.
- `Claim`: every attribute statement with provenance `{source_id, url, retrieved_at, extractor_version, confidence, raw_hash}`.
- `RelationshipEdge`: typed — `coworked_history` (CRM-derived), `shared_employer_now`, `customer_colleague`, `co_traveled_deal` (CRM-derived). Every edge carries an evidence type; unverifiable edges are not shipped.
- `SignalEvent`: the observable output (§6 F2–F4).

### 7.2 ER pipeline
1. **Blocking:** domain/email canonicalization; name+employer keys; phonetic keys; geographic canopies. Recall of the blocking layer is *measured*, not assumed (recall@blocking ≥99% on golden set).
2. **Candidate generation** → **pairwise scorer:** GBDT over engineered features (name similarity, email/domain evidence, title-history consistency, employer overlap, temporal consistency). Cheap, deterministic-ish, auditable.
3. **Clustering:** canopy + connected components with **must-not-link constraints** (conflicting evidence: simultaneous distinct employers, divergent publicly stated identities). LLM-cluster-free by design.
4. **Confidence bands:** ≥0.995 auto-merge · 0.90–0.995 human review queue (surfaced to *our* ops first, customers only via audit trail) · <0.90 no merge.
5. **Feedback flywheel:** customer accept/reject on writeback merges = labeled data → retrains scorer monthly. Graph quality compounds with customers — the network effect that raw-data vendors never build.
6. **Erasure cascades:** GDPR/CCPA deletion requests propagate through merged clusters using the same graph machinery — engineered as a feature ("compliance-grade identity"), not a patch.

### 7.3 Source mix (legality-first)
| Share | Source | Notes |
|---|---|---|
| Anchor | Customer CRM first-party data | Day-1 value; anchor entity set; feedback labels |
| High | Licensed commercial feeds (multi-vendor) | Pay for the rights; never single-vendor dependent |
| High | Public web: job boards, filings, press, company blogs, funding announcements | Crawl + extract; semantic-search craft lives here |
| Medium | Developer signals: GitHub, package registries, conference speaker lists (public) | Strong for technical personas |
| Excluded | LinkedIn scraping/automation, B2C data, purchased email lists | Hard no |

### 7.4 Evaluation harness (the moat is the measurement)
- Golden sets per source type; per-source precision/recall published to customers on a dashboard — **we publish our precision because competitors can't**. This is the wedge against ZoomInfo/Apollo trust decay.
- Canary accounts (known-champions set) run continuously; TTR (time-to-report) and coverage tracked daily.
- Event precision measured by customer feedback (useful/not-useful + confirmed/rejected), 90-day rolling, shown in-app.

---

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Freshness | job_change detection: median TTR ≤7d, p90 ≤14d; org attributes ≤30d; event fan-out ≤15 min |
| Trust | event precision ≥98%; merge precision ≥99.5%; provenance completeness 100% (no event without claims) |
| Scale | 50M nodes / 500M claims at GA; ER batch: 1M CRM contacts <24h; API p95 <300ms |
| Compliance | B2B contacts only; GDPR legitimate-interest DPIA + DSAR tooling + erasure cascades; CCPA; EU personal-data minimization; SOC 2 Type I by M9, Type II by M15 |
| Security | Customer CRM read-only by default; writeback opt-in + field-level allowlist; secrets in KMS; per-tenant data isolation; tenant data never trains shared models without consent |
| Reliability | 99.9% API uptime; stream delivery at-least-once with idempotency keys |

---

## 9. Competitive landscape

| Player | What they are | Gap we exploit |
|---|---|---|
| ZoomInfo (+ Tracker, Agent Teams/DoubleO.AI) | Decaying database + bolted-on agents | ~1% growth, 89% NRR; stale-data trust decay; closed; agents on a wrong graph |
| Apollo | Cheap breadth, PLG | 15–30% bounces; no identity rigor; no provenance |
| Clay | Workflow orchestration (system of action) | Needs a truth layer — **partner, not competitor**; their waterfall is our distribution |
| UserGems / Champify | Champion-tracking point solutions | Pointwise matching, closed products, no graph, no destination intelligence depth; $15–40K price umbrella under us |
| Common Room / Unify | Community/intent signals | Signal breadth without entity resolution; alerts without identity trust |
| PDL / Coresignal | Raw data APIs | Commodity rows; no resolution, no freshness SLA, no workflow |
| Beamery / Eightfold | Talent KGs (enterprise HR) | Validates graph approach; enterprise-priced, HR-motion; leaves GTM open; our phase-3 beachhead is their mid-market gap |
| Tamr / Graphify Labs | MDM ER / horizontal KG engines | Platform motions, not GTM-shaped; wrong buyer, wrong ontology |

**Positioning sentence:** *"Champion trackers without a graph lie eventually. Data vendors without workflows die slowly. We're the graph the workflows trust."*

---

## 10. Go-to-market & pricing

**Motion:** PLG diagnostic (Graph Audit) → design-partner depth → API/platform expansion via the Clay + GTM-engineer ecosystem.

**Pricing (v1):**
- **Graph Audit:** free. Self-qualifying.
- **Signal:** $1,500/mo (≤250 monitored accounts, 5 seats) · $3,500/mo (≤1,000 accounts, 15 seats, API + reverse ETL). Annual, land on the UserGems/Champify budget line ($15–40K umbrella).
- **Platform (M6+):** consumption — ~$0.002 per resolved entity, ~$0.05/entity/mo change-stream subscription, Snowflake share licensing, Clay-block revenue share.
- **Design partners (first 10):** 50% off for 12 months in exchange for feedback cadence + feedback-loop rights + case studies.

**Buyer personas:** (1) RevOps lead — owns the pain, signs the wedge; (2) GTM engineer — assembles stacks, adopts the API, evangelizes internally; (3) VP Sales — funds what sources warm pipeline; (4) [phase 3] staffing-firm ops — same graph, talent nouns.

### 10.1 Market sizing (bottom-up, assumptions explicit — revise with real data at M2)

- **Wedge SAM (~$200M):** B2B companies in NA+EU, 100–5,000 employees, sales team ≥10: ~25,000 firms (cross-check: ZoomInfo's historical ~30K paying base, Apollo's paying subset). Assume ~30% carry a champion/intent/signal budget today → ~7,500 accounts × $25K blended ACV ≈ $190M.
- **Platform TAM (~$3B today, $6B+ by 2029):** the GTM data + orchestration slice — ZoomInfo ~$1.2B, Apollo ~$265M, Clay ~$100M+ and compounding, plus Cognism/Lusha/Demandbase/6sense. The "truth layer" captures enrichment + signals + agent-identity spend as those budgets consolidate.
- **SOM (3-year):** 250–350 wedge + platform accounts × ~$30K blended ACV = **$8–10M ARR** — the seed-to-A bridge.

### 10.2 Unit economics (targets, instrumented from M1)

| Metric | Target | Basis |
|---|---|---|
| Gross margin | 70–75% at scale | data licensing 15–20% of revenue, infra 5–8% (warehouse-push model keeps compute on the customer's side) |
| Blended CAC | ≤$15K | Graph Audit PLG carries the top of funnel; sales-assisted deals modeled at ~$35K |
| ACV | $25K wedge → $45K by account year 2 | consumption expansion (API/stream/warehouse) lifts mature accounts |
| CAC payback | ≤9 months | PLG-assisted motion |
| NRR | ≥120% by M18 | seat→consumption migration + monitored-account growth |
| COGS floor | licensing ≥3 independent vendors, ≤$150K/yr aggregate pre-scale | multi-vendor clause is also risk mitigation (§13.1) |

### 10.3 Seed plan (assumes §15 decisions)

- **Raise:** $3.5M seed, opened after M2 gate evidence (precision ≥97% + 10 alert→meeting stories), closed by ~M5.
- **Use of funds:** 55% product/eng (data/ER engineer hire #1, platform engineer hire #3 at ~M6, data-ops contractor from M0) · 20% GTM (founding AE hire #2 + Audit-driven content) · 15% data licensing + privacy counsel retainer + SOC 2 · 10% buffer.
- **Runway:** 24 months. **End-of-runway state:** $1.2–1.5M ARR, 10+ external API consumers, SOC 2 Type II in progress, talent-graph pilot data in hand — funds the A on platform proof, not on wedge alone.

| Period | Accounts | ARR | Stage gate |
|---|---|---|---|
| M6 | 10 design partners | ~$75K | precision dashboard public |
| M9 | 18 | ~$150K | API beta + SOC 2 Type I |
| M12 | 30 | ~$350K | platform GA + consumption billing |
| M15 | 55 | ~$600K | 10 API consumers, NRR ≥110% |
| M18 | 90 | ~$1.2M | NRR ≥120%, talent-graph pilot signed |

---

## 11. Success metrics

| Class | Metric | Target |
|---|---|---|
| Trust | Event precision (customer-validated) | ≥98% by M6 |
| Trust | Merge precision (audit sample) | ≥99.5% from M1 |
| Coverage | CRM contacts resolved | ≥85% within 7d of import |
| Coverage | job_change detection vs. canary set | ≥70% by M6 |
| Speed | Median TTR on job changes | ≤7d |
| Activation | Time-to-first-validated-event | <48h |
| Business | Validated "alert → meeting" stories (design partners) | ≥25 by M9 |
| Business | Design-partner ARR | ~$150K by M9; $500K by M15 |
| Business | NRR | ≥120% by M18 |
| Platform | External API consumers | ≥10 by M12 |

---

## 12. Rollout (gated by measured acceptance, not calendar)

*Indicative calendar: M0 = 2026-12-01 kickoff; gates land ~M2 Feb 2027, ~M5 May 2027, ~M9 Sep 2027, ~M12 Dec 2027. Calendar slips before gates do.*

- **M0–M2 (Resolve):** 5–10 design partners signed; F1 import/resolution live; Graph Audit shipped; precision instrumentation from day one. *Gate:* resolution ≥80% + merge precision ≥99.5% on 3 partner CRMs; zero privacy incidents.
- **M3–M5 (Observe):** F2/F3 live for all partners; published precision dashboard; canary TTR reporting. *Gate:* precision ≥97% + 10 documented alert→meeting stories.
- **M6–M9 (Act + platform beta):** F4 warm path, F6 API/Clay/reverse-ETL, F7 MCP beta, SOC 2 Type I. *Gate:* 2 external integrations live; TTR p50 ≤7d; 5 MCP consumers.
- **M10–M12 (Platform GA + second-market probe):** consumption billing; 2 staffing-industry design partners on the same engine (talent nouns); seed raise or bridge decision point with real platform-usage data.

---

## 13. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Data-sourcing legality/ToS** (existential for data companies) | Source mix §7.3; no LinkedIn automation; privacy counsel retained before first customer-facing event; DPIA documented; erasure cascades engineered early and marketed as a feature |
| 2 | Incumbent response (ZoomInfo Agent Teams exists) | We are the layer *under* everyone incl. Clay-centric stacks; publish precision; they fight NRR decay with wall-street constraints, we compound eval flywheels |
| 3 | Clay builds/buys ER | Partner-first (be a first-class Clay data partner; their model is orchestrating data partners); worst case = category validation with distribution leverage lost |
| 4 | Point solutions (UserGems/Champify) copy or out-position | Compete on resolution quality, destination intelligence, openness; treat them as BD/acquisition counterparts who need our graph |
| 5 | Better LLMs commoditize matching | Identity is systems work (blocking, constraints, evals); we consume better models for extraction — model-agnostic by architecture |
| 6 | Cold start / seed-quality | CRM import is the anchor entity set; Graph Audit makes day-1 value independent of our crawl breadth |
| 7 | Champion fatigue (alerts ignored) | Precision bar + per-alert provenance + in-market ranking; alert volume caps per rep per week |

---

## 14. Alternatives considered & rejected (same founder, same timing)

| Alternative | Why rejected |
|---|---|
| AI SDR / outbound agent | Category collapsed (70–80% churn, inflated ARR, deliverability damage); agents are commodity; memory is moat |
| Talent graph first | Enterprise locked by Beamery/Eightfold; ATS import is weaker day-1 than CRM import; GTM buyers move faster; staffing mid-market is the phase-3 beachhead, not the beach |
| Corp-dev relationship CRM | Affinity owns it; proves relationship-graph WTP but leaves no gap worth attacking head-on |
| Horizontal KG engine (Graphify lane) | Platform-sales motion this profile doesn't imply; long sales cycles; GTM-shaped wedge reaches revenue in months, not years |
| Buying-committee / org-chart product | The only fresh org-chart source is LinkedIn — legally fraught; deferred until first-party edge mass exists |

---

## 15. Decisions (filled — defaults committed, reversal triggers stated)

1. **Name: "Substrate" committed for all internal artifacts.** Parity's Substrate (blockchain SDK) is a different class, but the space is crowded — trademark + USPTO screen and domain acquisition (target: `substrate.gtm` / `getsubstrate.com`) are a hard gate before any public artifact. Ranked fallbacks: Underlay → Lodestone → TrueBase.
2. **GTM-facing co-founder: recruit before the seed, not after.** Profile: sold into RevOps/sales leadership, carried quota at a data/intel vendor (ZoomInfo/Apollo/Gong/UserGems pedigree), personally willing to run design-partner sales. The wedge is sold, not just used. *Reversal trigger:* if no co-founder closes by M1, convert to hire #2 (founding AE) and revisit at the seed.
3. **Warehouse strategy: API-first; Snowflake share at M6; Native App evaluated at the M9 gate** — design-partner loop speed beats enterprise unlock sequencing.
4. **Fundraise: yes — $3.5M seed on post-M2-gate evidence** (velocity game against incumbent decay and Clay's partner window; bootstrap-to-profit forfeits the window). Terms detail in §10.3.
5. **First 10 design partners: 6 UserGems/Champify payers** (proven budget, switching motion) **+ 4 Clay-heavy GTM teams** (platform halo, Clay-block feedback). Verticals: dev-tools, fintech SaaS, HR-tech SaaS — high champion-mobility, long account lifetimes. Staffing stays out until the M12 probe (§12).

**Residual judgment calls surfaced during build (ops decides, no re-litigation of the five above):** per-rep alert caps (default 5/week), design-partner data-retention (24 months), writeback field allowlist (contact fields only, v1).

---

## 16. Appendix — research notes & sources (2026-11-12)

- Clay trajectory: $1M→$100M ARR in ~42 months, Series D $115M at $7.1B (Sept 2026), ~17K customers — Clay blog / ARR Club / SaaSRise / Built In coverage (search-surfaced).
- ZoomInfo: ~$310M quarterly revenue +1.2% YoY, NRR 89%, goodwill impairment, stale-data complaints; Tracker launch (2022) and Agent Teams via DoubleO.AI (Oct 2026) — [Tracker press release](https://ir.zoominfo.com/news-releases/news-release-details/zoominfo-launches-tracker-help-companies-retain-visibility-key), [Agent Teams press release](https://ir.zoominfo.com/news-releases/news-release-details/zoominfo-introduces-agent-teams-powered-acquisition-doubleoai).
- Apollo: [$150M ARR announcement](https://www.apollo.io/magazine/apollo-reaches-150-million-arr-fueled-by-ai), [Sacra ~$265M ARR estimate](https://sacra.com/research/apollo-at-265m-arr), 15–30% bounce-rate reviews, LinkedIn page delisting (early 2025).
- AI SDR backlash: [TechCrunch-reported 11x ARR scrutiny via InScaler account](https://www.inscaler.com/blog/i-tried-canceling-ai-sdr-contract-with-11x), [AI SDR post-mortem](https://deathtocoldemails.com/ai-sdr-post-mortem), [contrarian analysis 2026](https://www.digitalapplied.com/blog/case-against-ai-sdrs-contrarian-analysis-2026), [buyer scrutiny guide](https://salesmotion.io/blog/ai-sdr-claims-scrutiny-what-buyers-should-verify), [r/AskGTM churn thread](https://www.reddit.com/r/AskGTM/comments/1u471y7/everyone_bought_ai_sdrs_in_2025_in_2026_the_churn).
- Signal-based selling / GTM engineering: [Apollo GTME framework](https://www.apollo.io/insights/signal-based-selling), [Factors.ai GTME trends 2026](https://www.factors.ai/blog/gtm-engineering-trends), [Onfire GTME job data (~3K open roles)](https://www.onfire.ai/blog/gtm-engineering-data), [RevPartners GTME vs RevOps](https://blog.revpartners.io/en/revops-articles/gtm-engineering-vs-revops).
- Champion tracking: [UserGems contact tracking](https://usergems.com/product/contact-tracking), [Champify champion tracking](https://champify.io/platform/champion-tracking) (UserGems ~$40K+/yr; Champify $15–30K SMB; no acquisition between them).
- Raw data commodity: [Coresignal pricing](https://coresignal.com/pricing), [Coresignal vs PDL](https://coresignal.com/coresignal-vs-peopledatalabs), PDL tiers ~$98–600/mo.
- Landscape checks: [Graphify Labs (YC S26)](https://www.ycombinator.com/companies/graphify-labs), [Graphiq — KGs for GTM](https://graphiq.ai/resources/knowledge-graphs-gtm), Tamr (enterprise MDM ER), Beamery/Eightfold talent KGs.
