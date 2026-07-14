#!/usr/bin/env bash
# ===========================================================================
# go_paper.sh — ONE command to return AurvexAI to PAPER (no real orders).
#
#     bash scripts/go_paper.sh
#
# Idempotent, no confirmation needed (safe direction). What it does:
#   1. Applies the validated deployment config (same block as go_live).
#   2. Disarms via arm_live.py --disarm: AX_MODE=paper + LIVE_ENABLED=false +
#      LIVE_SEND_ORDERS=false. Your secrets in .env are untouched.
#   3. Rebuilds + recreates BOTH engine and dashboard.
#   4. Verifies: mode=paper · real sends disarmed.
#
# NOTE: this does NOT reset the balance/ledger. To also wipe the paper ledger
# for a clean start, run first:  docker compose down -v
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo "════════ 1/3  apply validated config + DISARM (paper) ════════"
python3 scripts/apply_fast_paper_env.py --apply
python3 scripts/arm_live.py --disarm --apply

echo
echo "════════ 2/3  rebuild + restart engine + dashboard ════════"
docker compose up -d --build --force-recreate

echo
echo "════════ 3/3  verify ════════"
sleep 8
docker compose logs --tail=60 engine 2>/dev/null \
  | grep -iE "starting mode|real sends" \
  || echo "(re-check: docker compose logs --tail=40 engine)"
echo
echo "EXPECTED: 'engine starting mode=paper' · 'real sends disarmed'."
