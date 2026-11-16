"""Source layer (W5–6): crawlers, licensed feeds, LLM extraction gateway.

Hard lines (repo invariants):
  * LLMs extract and normalize ONLY — identity is never decided here
  * every claim carries provenance: source_type + source_id/url + retrieved_at
  * no secrets in code: feed/LLM keys arrive via SUBSTRATE_* env only
  * B2B professional data only; robots.txt honored on every crawl
"""
