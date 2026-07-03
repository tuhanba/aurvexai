# TEST EVIDENCE — final execution pack (verification wave)

Date: 2026-07-03. Baseline: `main` @ `832723b` (PR #17).
Verification environment: clean isolated clone (cloud session), Python 3.x,
offline (no keys, no network trading calls).
Items that can only be measured on the engine host are marked
**PENDING-ON-HOST** with the exact command to run — they were deliberately
not faked here.

## 1. Test suite (green floor)

```
$ python -m pytest
596 passed in 8.35s
```

- Floor is **596 passed, 0 skipped** — matches the pack's hard floor.
- Re-run after this wave's changes (dashboard template polish + docs):
  **596 passed** — no test deleted, weakened, or skipped.
- Parity tests (`test_paper_live_parity.py`) untouched and green.

## 2. Offline end-to-end demo

```
$ python main.py demo
... engine stopped after 40 cycles (balance 200.00 → 195.62, trades executed,
    funnel/journal/shadow rows written)
```

Definition-of-done item "offline demo completes end-to-end" holds.

## 3. Dashboard endpoint checks (against local demo data)

Local `python main.py dashboard` on the demo DB — structure checks only
(host values differ after the fresh-epoch reset):

| Endpoint | Result |
|---|---|
| `/health` | 200; four independent truths present (`engine_alive`, `data_fresh`, `kill_switch`, `mode_ok`), `heartbeat_stale_ms=120000` |
| `/api/status` | 200; balance, profit-lock fields (`daily_profit_lock_*`), mode banner fields present |
| `/api/binance` | `keys_absent` (no key configured in this environment — correct fail-soft) |
| `/` (dashboard) | Renders; **four status badges + full-width PAPER banner confirmed by screenshot**; zero browser console errors |

**Dashboard defect found and fixed in this wave:** the shipped `index.html`
declared `const mb` twice inside `refresh()` (mode banner + missed-opportunity
buckets) — a JavaScript `SyntaxError` that prevented the ENTIRE dashboard
script from parsing, so no panel ever populated. Verified with `node --check`
before (fails) and after (passes) the rename, and by headless-Chromium
screenshots showing live data with zero console errors. Template-only fix;
no API or engine change.

Host re-check (after fresh-epoch restart): **PENDING-ON-HOST**

```
curl -s http://127.0.0.1:5000/api/status
curl -s http://127.0.0.1:5000/api/binance
curl -s http://127.0.0.1:5000/api/system_state
curl -s http://127.0.0.1:5000/api/trades/open
```

Checklist to record on host: trade count 0 (or today-only); balance = 200;
profit-lock target = 20.00 USDT; `/api/binance` NEVER `unsafe_key`; Telegram
engine-start + binance-status each prefixed `[PAPER]`; no key substring in
any endpoint body.

## 4. Cycle p95 / `HEARTBEAT_STALE_MS` — PENDING-ON-HOST

Requires ≥ 30 min host uptime after the reset:

```
sqlite3 -readonly ~/aurvexai/data/aurvex.db "SELECT COUNT(*), CAST(AVG(cycle_ms) AS INT), MAX(cycle_ms) FROM funnel"
```

Rule: if p95 wall time > ~20 000 ms → set `HEARTBEAT_STALE_MS` to 6× observed
p95 in `.env` and record that a second restart is the owner's call. Otherwise
the default (120 000 ms) stands. Record the measured value here.

## 5. Dry-run payload validation — PENDING-ON-HOST (needs read-only key)

```
docker exec aurvex-engine python scripts/dryrun_report.py
python scripts/dryrun_report.py --db aurvex_backup_pre_reset.db
python scripts/daily_report.py  --db aurvex_backup_pre_reset.db
```

If no read-only key is configured: mark BLOCKED-on-owner. Known finding to
confirm or clear: whole-coin `step_size` symbols can round 30%/20% TP
fractions of small positions down to zero quantity — if real symbols FAIL,
record as sizing-input evidence for a future Stage-3 discussion (fix belongs
to sizing inputs / min-notional config, NOT frozen exit logic, NOT this wave).

## 6. Secret sweep

```
$ git grep -nIiE "(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/]{20,}" -- ':!*.md'
(no matches)
$ git check-ignore .env
.env            # ignored — and no .env file exists in the repo/clone
```

Clean: no hardcoded secrets; `.env` gitignored and absent.

## 7. Frozen-path assertion

This wave touched only: `src/aurvex/dashboard/templates/index.html`
(presentation + the `const mb` fix), `RISK_MODEL.md`, and the three report
files. `setups.py`, `scoring.py`, `quality.py`, `risk.py`, `decision.py`,
`executors.py`, shadow logic: **zero changes** (verify with `git diff
--stat 832723b..HEAD`).
