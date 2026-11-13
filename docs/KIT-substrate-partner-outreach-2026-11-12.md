# KIT: Substrate design-partner outreach kit (W1 dependency)

**Date:** 2026-11-12 · **Status:** draft for review · **Parent:** [PLAN-substrate-m0-m2-execution-2026-11-12.md](PLAN-substrate-m0-m2-execution-2026-11-12.md) §10 · **PRD §15 decision #5 governs targeting**
**Owner:** GTM lead (co-founder or hire #2) · **Goal:** 10 signed design partners by W4; first Audit delivered within 48h of each connect

**The one-sentence pitch used everywhere:** *"We resolve every champion you ever lost track of and tell you the week they move — with a published precision number, so the alerts stay trustworthy."*

---

## 1. ICP — two segments, 10 slots total

### Segment A — "Switchers" (6 slots)
Teams already paying for champion/job-change tracking ($15–40K budget line **proven**) but dissolving trust in it.

| Dimension | Qualifier |
|---|---|
| Company | B2B SaaS, 100–1,000 employees |
| Sales team | 10–60 AEs/SDRs, outbound or ABM motion |
| ACV | ≥$10K (champion re-engagement economics work) |
| Vertical | dev-tools, fintech SaaS, HR-tech SaaS (high champion mobility — PRD §15) |
| Current spend | UserGems, Champify, or ZoomInfo Tracker on the stack |
| CRM | 5+ years of Salesforce or HubSpot history with closed-lost volume |
| Disqualify | agencies/studios; <2 years CRM history; no closed-lost data; legal/medical (privacy-counsel friction kills the M0 window) |

### Segment B — "Clay-heavy GTM teams" (4 slots)
Teams living in the workflow layer, feeling the data-quality abyss daily.

| Dimension | Qualifier |
|---|---|
| Company | B2B SaaS or AI-native company, any size 100–2,000 |
| Stack signal | 4+ Clay workflows in production **and/or** a GTM engineer on staff |
| Pain fit | multi-vendor waterfall enrichment; complaints about bounce rates/dupes |
| CRM | Salesforce or HubSpot, active enrichment writes |
| Disqualify | pure-PLG self-serve motions (no pipeline reviews to feed); e-commerce |

**Buyer map (both segments):** RevOps lead signs · GTM engineer champions and adopts the API · VP Sales funds what sources warm pipeline. Sequence touches the GTM engineer first if identifiable (they have the pain and the audience); RevOps first otherwise.

---

## 2. Target list — build it this week (W1), 40 accounts → 10 signed

Sourcing methods, in priority order:

1. **Vendor-switch evidence:** UserGems/Champify case-study pages + G2 review texts mentioning *switching* (the "we started on X, moved to Y" pattern); practitioner posts describing the same migration.
2. **Stack-in-job-posts:** job postings listing UserGems/Champify/Clay in the stack (job-board search across the 3 ICP verticals).
3. **Clay ecosystem:** Clay community participation, Clay University alumni roles, GTM-engineer titles mentioning Clay.
4. **Warm paths first:** mp + GTM lead's own networks — any past colleague now in RevOps/GTME at an ICP account jumps the queue.

**Sheet columns (one row per account):** `name · segment · budget-holder (name/title) · GTM engineer (name/title) · CRM (SF/HS) · entry story · seq (A/B/C) · status · next-touch date · Audit status · verdict`.

Cadence: 40 built W1 → 20 sequenced W2 → 10 signed W4 (two partners/week from W2 on; switchers close faster than Clay teams).

---

## 3. Outreach sequences

**Channel rules (PRD hard lines):** email + communities + referrals only. **No LinkedIn automation, ever.** Volume caps: 20 first-touches/week while the product is pre-gate; every reply gets a same-day response; every "no" gets one graceful close.

### Seq A — Switchers (3 touches over 10 days)

**Touch 1** · Subject options: `the alerts you muted` / `your champion tool's precision number`
> Quick one, [Name] —
>
> Most teams running [UserGems/Champify] tell us the same thing: the first false "your champion moved!" alert trains the whole floor to ignore the channel. The tools don't publish a precision number, so you can't even measure how much you're ignoring.
>
> We built Substrate differently — identity resolution with a published precision figure (we're holding ≥98% on customer-validated events). And I'd rather show than tell: point us at your CRM read-only, and in 48 hours you get a free Graph Audit — how much of your contact base actually resolves, what share of titles are stale, and how many past champions changed jobs in the last 90 days.
>
> If the report isn't interesting, keep the report and delete us. Worth 20 minutes?

**Touch 2** (day 4, reply-in-thread) · Subject: `re: the alerts you muted`
> One concrete number while you decide: across our first design-partner CRMs, teams typically find 150–300 past champions who moved in the last 90 days — most unbeknownst to the current owner of the account. The Audit quantifies exactly that on your data, plus the resolution and staleness rates your current tool never reports. Read-only, no contract, report is yours.

**Touch 3** (day 10) · Subject: `closing the loop`
> Last nudge — if champion re-engagement isn't a priority this quarter, all good. The Audit offer stands for a month if it becomes one. I'll stop here either way.

### Seq B — Clay-heavy GTM teams (3 touches over 10 days)

**Touch 1** · Subject options: `your waterfall has no confidence score` / `which enrichment row do you trust?`
> [Name] —
>
> Your Clay columns chain [ZoomInfo → Apollo → whoever] per row, and nothing tells you which vendor's answer to believe when they disagree. That's not a Clay problem; it's that the layer underneath has no identity resolution and no provenance.
>
> That layer is what we're building: a resolved, bitemporal GTM graph — every claim carries its source and timestamp, changes stream out as typed events.
>
> Before we ship the Clay block, we're running free Graph Audits for heavy Clay teams: it quantifies your enrichment conflict rate and contact-resolution rate on your own CRM. You'd also get the Clay block in early access. 20 minutes of read-only access — want the Audit?

**Touch 2** (day 4): lead with the methodology — link the precision-dashboard philosophy ("we publish per-source precision/recall; vendors hide it because they can't measure it"), offer 15 minutes with the GTM engineer's workflow in mind.

**Touch 3** (day 10): breakup + Clay-block waitlist invitation (keeps the door open without pressure).

### Seq C — Communities & warm paths (always-on)

- One methodology post per month in GTM-engineering communities (the Graph Audit report structure itself is the content — "here's how to audit your own CRM identity layer; or send it to us and we'll run it free").
- Podcast/operator-newsletter angle: pitch the "publish your precision" thesis, not the product.
- Referral: every signed partner gets 2 Audit credits to hand to peers (untracked, no gift-card nonsense).

**Reply-handling rules:** interest → send the Audit intake link + 48h SLA. "Send pricing" → yes ($1,500/mo tier, 50% off as design partner, terms attached). "We already have X" → ask what their false-alert rate is; schedule only if they know the number or admit they don't. "No" → close gracefully, tag for the M6 audit-based re-approach.

---

## 4. Graph Audit landing copy

**Headline:** `Your CRM is lying to you. Here's the audit.`
**Sub:** `Substrate runs a free, read-only audit of your Salesforce or HubSpot — and shows you in 48 hours how much of your go-to-market data actually resolves to real, current people.`

**The three findings it reports:**
1. **Resolution rate** — what % of your contacts resolve to live, current professional identities (and what % are duplicates wearing wigs).
2. **Staleness** — what % of titles/employers are out of date, measured against sources with timestamps — not vibes.
3. **Lost champions** — how many people who ever touched your pipeline changed jobs in the last 90 days, and how many landed somewhere hiring.

**Form:** work email → read-only OAuth connect (or CSV export). **Privacy block (verbatim on the page):** *Read-only access. B2B professional contacts only — never consumer data. Your data is used to produce your report and to improve resolution quality under our design-partner terms; deleted within 30 days of report delivery on request, erasure honored cascade-wide.*

**CTA variants (A/B):** `Run my free audit` / `See what my CRM is hiding`.

---

## 5. Design-partner agreement — key terms (term sheet; counsel drafts the contract)

| Term | Value |
|---|---|
| Price | Signal tier $1,500/mo → **$750/mo** (50% off) for 12 months, then standard pricing or churn |
| Our deliverables | weekly working session first 4 weeks, monthly after; precision dashboard access; feature-request lane with 2 reserved roadmap slots |
| Partner deliverables | a named RevOps/GTME point of contact; 👍/👎 verdict on every alert (this is the precision dataset); one 60-min exec interview |
| Data terms | read-only CRM by default; writeback opt-in with field-level allowlist (contact fields only in v1); B2B contacts only; 24-month retention; GDPR/CCPA commitments incl. erasure cascades; partner data never trains shared models without written consent |
| Our rights | aggregate, de-identified learnings; feedback-derived labeled data for ER training; case study **by mutual approval**; trademark use only with consent |
| No exclusivity · partner may disclose price · 30-day exit · no data lock-in (full CRM export on exit, CSV or via their warehouse) |

---

## 6. Partner onboarding — first 48 hours (checklist)

1. Signed term sheet → Slack Connect channel + Audit intake link.
2. Read-only CRM connect (CSV fallback) → import run same day.
3. **Graph Audit delivered within 48h** — the first trust artifact; walk them through it live, don't send a PDF into the void.
4. Alert preferences: channel, per-rep cap (default 5/week), writeback allowlist review.
5. Success metric agreed in writing per partner (default: *1 re-engaged-champion meeting within 60 days*).
6. Verdict mechanism confirmed in the channel (👍 = validated, 👎 = false positive — both are data).

---

## 7. M0 kickoff checklist (ops, day one — 2026-12-01)

| # | Item | Owner | Done-by |
|---|---|---|---|
| 1 | Privacy counsel retained; term sheet + DPA review started | mp | W1 |
| 2 | Coresignal + PDL contracts signed **with cancellation clause** | mp | W2 |
| 3 | Terraform bootstrap + managed Postgres up (PLAN §2) | tech founder | W1 |
| 4 | SFDC/HubSpot read-only adapters working against sandbox orgs | tech founder | W2 |
| 5 | Golden-set labeling calendar block (2 founder-days) | tech founder | W3 |
| 6 | 40-account target sheet built (this doc §2) | GTM lead | W1 |
| 7 | Audit landing page live (this doc §4) | GTM lead | W2 |
| 8 | First 3 Audits delivered | GTM lead | W4 |

---

**Completion note:** this kit closes the M0-ready document set (PRD → PLAN → KIT). The next artifacts are *code* (M0–M2 build per PLAN §7 — worktree lanes through the rig gate) and the pitch deck, which stays deferred until M2 evidence exists per PRD §12.
