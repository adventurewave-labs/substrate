"""Signals (W7–8): job-change detection, delivery, canary replay.

Hard lines (repo invariants):
  * detection is deterministic snapshot diffing — never an LLM judgment
  * events carry idempotency keys: replays never duplicate
  * delivery is at-least-once; the event row is the source of truth, sinks are
    best-effort copies
"""
