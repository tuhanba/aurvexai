#!/usr/bin/env bash
# ===========================================================================
# go_live.sh — ONE command to take AurvexAI LIVE (real Binance USDT-M orders).
#
#     bash scripts/go_live.sh
#
# Idempotent. What it does:
#   1. Applies the validated deployment config (strategies, risk, profit-lock,
#      regime, universe — the same env that drives dashboard + Telegram) via
#      apply_fast_paper_env.py. Any manual edits to CONFIG keys are reset to the
#      known-good block; secrets are never touched.
#   2. Arms real orders via arm_live.py: sets AX_MODE=live + LIVE_ENABLED +
#      LIVE_SEND_ORDERS, keeps your token/keys. This is the ONLY interactive
#      step — you type the confirmation phrase (real money, on purpose).
#   3. Rebuilds + recreates BOTH engine and dashboard so they load the new .env.
#   4. Verifies: mode=live · real FUTURES wallet balance synced · real sends ARMED.
#
# Rollback to paper any time:  bash scripts/go_paper.sh
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo "════════ 1/4  apply validated config (strategies/risk/dashboard/telegram) ════════"
python3 scripts/apply_fast_paper_env.py --apply

echo
echo "════════ 2/4  ARM LIVE — real orders (confirm when prompted) ════════"
python3 scripts/arm_live.py --apply

echo
echo "════════ 3/4  rebuild + restart engine + dashboard ════════"
docker compose up -d --build --force-recreate

echo
echo "════════ 4/4  verify (waiting ~10s for startup + real balance read) ════════"
sleep 10
echo "---- engine state ----"
docker compose logs --tail=100 engine 2>/dev/null \
  | grep -iE "starting mode|equity synced|real sends|real balance read" \
  || echo "(no state lines yet — re-run: docker compose logs --tail=60 engine)"
echo
echo "EXPECTED: 'engine starting mode=live' · 'LIVE equity synced to real wallet"
echo "balance: <your real futures balance>' · 'real sends ARMED'."
echo "If you see 'real balance read FAILED' the server can't reach Binance —"
echo "entries stay BLOCKED (safe); check API keys / connectivity."
