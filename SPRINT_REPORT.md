# SPRINT_REPORT — LIVE-READY SPRINT (fresh epoch + full infra, engine core frozen)

Date: 2026-07-03 · Branch: `claude/aurvexai-live-ready-sprint-uv57se`

## Test green floor

- **Floor recorded before any change: 534 passed** (`pytest -q`, 0 skipped).
- **Final: 596 passed, 0 skipped** — floor + 62 new tests:
  - `tests/test_daily_profit_lock.py` (11)
  - `tests/test_binance_account.py` (9)
  - `tests/test_order_payload.py` (20)
  - `tests/test_dashboard_surfaces.py` (+7 Task-4 tests)
  - `tests/test_telegram_events.py` (10)
  - `tests/test_daily_report.py` (6)
- Parity tests untouched and green (`test_paper_live_parity.py` unchanged).
- Offline `python main.py demo` completes end-to-end (40 cycles).

## What shipped (one commit per task)

| Task | Commit | Summary |
|------|--------|---------|
| 1 | `23d5ed3` | Daily profit lock — additive filter right after the kill switch; UTC-day REALIZED PnL basis; reason exactly `daily_profit_lock`; heartbeat fields; resets at UTC rollover |
| 2 | `c5b3564` | Binance read-only account adapter (Stage 1) — GET-class only, optional, fail-soft; `symbol_filters` cache table; slow-timer refresh outside the cycle; `/api/binance`; withdraw-key self-check → `unsafe_key` |
| 3 | `a362179` | Dry-run order payload validation (Stage 2) — pure `order_payload.py` (rounding, validation, cancel/replace state machine, timeout table); `scripts/dryrun_report.py` → `DRYRUN_VALIDATION.md` |
| 4 | `95ffaef` | Dashboard risk terminal — four independent status badges, env-driven staleness cut, full-width mode banner, profit-lock/Binance/shadow panels, optional Basic auth |
| 5 | `5a627d6` | Telegram completeness — profit-lock alert (edge-triggered), kill-switch copy fix, binance status transitions, single-point `[PAPER]` mode tag |
| 6 | `bd5ed4d` | Daily verdict report — `scripts/daily_report.py` → `DAILY_REPORT.md`, read-only, bootstrap 95% CI, `--db` backup mode |

## Frozen-zone findings

**No bug found in any frozen zone.** All frozen files (`setups.py`, `scoring.py`,
`quality.py`, `risk.py` sizing core, `decision.py`, `executors.py` fill logic,
shadow decision logic) are untouched. `LiveExecutor._send_order()` remains the
`SIMULATED` stub; `LIVE_ENABLED=false`; no order intent anywhere.

One **observation** (not a bug, no patch needed): `scripts/dryrun_report.py`
run against the local demo DB showed that on symbols with a whole-coin
`step_size` (e.g. 1.0), small aggressive-paper positions can have their 30%/20%
TP fractions round DOWN to zero quantity — exactly the silent live-sizing
distortion Stage 2 exists to surface. Re-run the dry-run report on the server
once the Task-2 adapter has cached real exchange filters; if real symbols FAIL,
that is sizing-input evidence for any future Stage-3 discussion (fix would be
in sizing inputs / min-notional config, not in frozen exit logic).

## Duplicate-send sweep (Task 5)

No duplicate transport paths found: `system_started` fires once;
`trade_opened` branches (two-pass vs legacy) are mutually exclusive;
kill switch is day-keyed; binance status is transition-keyed in the adapter;
`trade_event` + `trade_closed` on the same bar are intentionally distinct
messages (fill detail + close summary), not a transport duplicate. No
transport-level fix required.

## Heartbeat staleness threshold (Task 4.2)

- New env: `HEARTBEAT_STALE_MS`, default `max(120000, 6 × CYCLE_INTERVAL_SEC × 1000)`
  → **120 000 ms at the default 20 s cycle**.
- Local reference measurement (offline demo, synthetic data, 120 cycles):
  min 12 / median 13 / p95 17 / max 21 ms — trivially inside the cut.
- **The server p95 must be measured on the engine host after deploy** (real
  ccxt round-trips dominate). One command, run after ~30 min of uptime:

```
sqlite3 -readonly ~/aurvexai/data/aurvex.db "SELECT COUNT(*), CAST(AVG(cycle_ms) AS INT), MAX(cycle_ms) FROM funnel"
```

  If p95 cycle wall time exceeds ~20 s (i.e. cycles overlap the interval),
  set `HEARTBEAT_STALE_MS` explicitly to `6 × observed_p95_ms` in `.env`.
  Until then the default stands. Record the measured value here post-deploy.

## Balance decision (Task 7.2)

Fresh epoch starts at `INITIAL_PAPER_BALANCE` (aggressive_paper default **200**).
If continuity from 205 is wanted, set `INITIAL_PAPER_BALANCE=205` in `.env`
BEFORE `docker compose up`. **Chosen value: ______ (owner fills at deploy).**

## Recommendations before the Task-7 deploy

1. Set `DASHBOARD_AUTH_USER` / `DASHBOARD_AUTH_PASS` in `.env` — the dashboard
   port is published to the internet; Basic auth is now supported and `/health`
   stays open for the docker healthcheck.
2. If running Stage 1: put a **read-only** Binance key in `.env`
   (`BINANCE_API_KEY` / `BINANCE_API_SECRET`). A key with withdraw enabled will
   be flagged `unsafe_key` on the dashboard and Telegram.
3. Keep the `"5000:5000"` publish for now (direct-IP access); the commented
   `127.0.0.1` alternative + SSH-tunnel recipe is in `DEPLOYMENT.md` §4a.

## Task 7 — deploy + fresh-epoch reset runbook (engine host)

> Executed on the engine host by the owner — this sprint's code work was done
> and tested in a remote workspace that has no access to the server or its
> Docker volume. ONE restart total. Commands one per line, never chained.

**Pre-check — is the volume DB contaminated with old-engine history?**

```
docker exec aurvex-engine sqlite3 -readonly /app/data/aurvex.db "SELECT MIN(open_time) FROM trades"
```

If the earliest trade predates the current epoch/deploy era → contaminated →
full-wipe path. If the owner already reset and the DB was created fresh today
→ already-fresh path (do NOT wipe today's clean data).

**Contaminated-DB path:**

```
cd ~/aurvexai
git pull origin claude/aurvexai-live-ready-sprint-uv57se
docker compose stop
docker cp aurvex-engine:/app/data/aurvex.db ./aurvex_backup_pre_reset.db
docker cp aurvex-engine:/app/data/aurvex.db-wal ./aurvex_backup_pre_reset.db-wal
docker compose down -v
docker compose up -d --build
docker ps
curl -s http://127.0.0.1:5000/health
```

(Step 4 "no such file" is harmless — a clean shutdown checkpoints the WAL.
Keep the backup file: it is the autopsy input for
`python scripts/daily_report.py --db aurvex_backup_pre_reset.db` and
`python scripts/dryrun_report.py --db aurvex_backup_pre_reset.db`.)

**Already-fresh-DB path:**

```
cd ~/aurvexai
git pull origin claude/aurvexai-live-ready-sprint-uv57se
docker compose up -d --build
docker ps
curl -s http://127.0.0.1:5000/health
```

**Post-deploy verification checklist (record results here):**

- [ ] dashboard shows FOUR badges (engine loop with raw heartbeat age /
      data freshness / kill switch / mode) and the full-width PAPER banner
- [ ] trade count 0 (or today-only); balance = chosen initial
- [ ] profit-lock panel: inactive, target = balance × 10%
- [ ] `/api/binance` returns the expected state (`keys_absent` without keys;
      `connected` with a read-only key; NEVER `unsafe_key`)
- [ ] Telegram received engine-start + binance-status messages, every one
      beginning `[PAPER]`
- [ ] one full engine cycle logged; heartbeat age < threshold on the badge
- [ ] measured server cycle p95 recorded in the staleness section above

## Standing safety verdicts (unchanged)

- `LIVE_ENABLED=false`; `LiveExecutor._send_order()` is the `SIMULATED` stub.
- Live Stage 3 (real orders) NOT authorized here; this sprint ships Stage 1
  (read-only) + Stage 2 (dry-run payload validation) only.
- `SCORE_AS_GATE=false`, `RISK_MODULATION_ENABLED=false` defaults untouched;
  shadow remains report-only (label hardcoded on the dashboard).
- Carry-wave files untouched.
- DB migrations additive-only; dashboard DB access read-only.
- No secrets in code/git/logs/dashboard payloads; the secret-exposure sweep
  now also covers `/api/binance` and asserts no key substring in the
  heartbeat row, adapter payloads, or any endpoint body.

## Blockers / skips

- **Task 7 execution (deploy + reset) is the only deferred item**: it requires
  the engine host (Docker volume + `.env` secrets), which this workspace
  cannot reach. Everything is committed, tested and runbook'd above; the
  restart remains exactly ONE.
- Nothing else skipped.
