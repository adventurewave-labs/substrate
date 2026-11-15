"""Entity resolution v0 — deterministic, precision-first.

Identity is never decided by an LLM (repo invariant). v0 is rules-only: blocking
generates candidates, deterministic rules emit auto_merge / review decisions, and
every decision lands in merge_decisions with its featureset_version.
"""
