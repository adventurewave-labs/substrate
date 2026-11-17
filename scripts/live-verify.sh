#!/usr/bin/env bash
# Live verification against a real Postgres (W9 housekeeping).
# Usage: SUBSTRATE_TEST_DATABASE_URL=postgres://... scripts/live-verify.sh
# Requires: .venv with dev deps at the repo root.
#
# ROOT resolves from THIS script's own location — never the caller's cwd or
# their git checkout (gate review, W9 r11: wrong-repository execution).
set -euo pipefail

: "${SUBSTRATE_TEST_DATABASE_URL:?SUBSTRATE_TEST_DATABASE_URL must point at a disposable Postgres}"

SCRIPT="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(dirname "$(dirname "$SCRIPT")")"

echo "== migrations =="
"$ROOT/.venv/bin/substrate" migrate --database-url "$SUBSTRATE_TEST_DATABASE_URL"

echo "== live roundtrip suite =="
"$ROOT/.venv/bin/pytest" "$ROOT/tests/test_live_db.py" -q

echo "== live suite PASSED =="
