# SESSION_WORK_REPORT.md — final scalp research + readiness pack

- **Date:** 2026-07-08
- **Branch:** `claude/aurvexai-scalp-research-prod-az1f4t`
- **Base commit:** `89ecba4` (merge of PR #34)
- **Commit hash of this work:** see `git log` on the branch (this file is
  committed with the work itself).

## What was inspected

- Full repo: git history (34 PRs), all 28 root documents, `src/aurvex/`
  engine code (allocation, engine cycle, filters, risk, funnel, dashboard,
  market_data, models, config), tests, scripts, Docker files.
- Verified against code, not prose: two-pass `GLOBAL_RANKING` +
  `RANK_KEY=edge` (follows measured score-bucket edge, neutral when N<100);
  per-cycle and per-symbol crash isolation; missing-timeframe skip (PR #30
  fix); heartbeat written at cycle end; dashboard freshness/kill/mode badges;
  min-notional / step-size clip reasons; kill switch + profit lock tests;
  shadow/score/risk-modulation all observe-only by default; five-gate live
  lock disarmed by default (`test_stage3_live_orders.py`).
- Found and fixed documentation drift (see below) — README/ROADMAP/
  LIVE_READY_CHECKLIST still described the pre-donchian era ("no strategy
  passes the evidence gate", "live executor is a stub").

## Research run this session (new, real data)

Final scalp wave over the families NO prior campaign had tested:
24 months (2024-07→2026-06) of real archive 5m/15m klines × 12 coins,
pre-registered rules, split-half holdout, taker+slip cost, no lookahead,
stop-first conservative fills, gross/net decomposition.

**Result: 12/12 cells NO-GO** — cross-symbol leader-lag (follow AND fade,
5m/15m), rejection-wick reversal, high-volume failed breakout, volume+range
impulse continuation, break-and-retest, inside-bar breakout, prior-day
sweep-reclaim. Best gross +0.08R; cost 0.2–0.6R; 0/12 coins positive in any
cell; both halves negative everywhere. Campaign-wide trial count now 88.
Full tables: `SCALP_EDGE_RESEARCH_REPORT.md`. **Scalp is closed as a
structural NO-GO, not parked.**

## What was changed (code)

1. **Stale-data entry guard** (`config.py`, `engine.py`) — new
   `STALE_ENTRY_GUARD_BARS` (default 3): if the freshest CLOSED
   signal-timeframe bar is >N bar-lengths behind wall clock, the symbol is
   skipped for new entries that cycle (funnel reject reason `stale_data`).
   Open-trade management untouched; synthetic provider exempt; 0 disables.
   This closes the one gap found in the data-flow audit (the dashboard
   flagged staleness but the entry path would still trade on it).
2. **Research harness archived** — `scripts/fetch_archive_klines.py`
   (data.binance.vision monthly fetcher, µs-timestamp defect guard) and
   `scripts/scalp_families.py` (the 12-cell campaign, reproducible).
3. **New tests** — `tests/test_stale_entry_guard.py` (7 tests: fresh passes,
   stale blocked, boundary, empty candles blocked, synthetic exempt,
   0 disables, default value).

## What was changed (docs — truth alignment)

- **NEW `SYSTEM_STATE.md`** — single source of truth (what works, what
  failed, what is paper-only, recommended `.env`, fastest valid setup).
- **NEW `SCALP_EDGE_RESEARCH_REPORT.md`** — every scalp family ever tested,
  all four campaigns, with verdicts and kill reasons.
- **NEW `SERVER_RUNBOOK.md`** — owner ops: start/stop/restart/logs/health/
  reset/backup/restore/update/Telegram/dashboard/Binance-key checks.
- **NEW `FINAL_OWNER_DECISION.md`** — the decisions (paper YES, live
  BLOCKED, exact `.env`, exact commands, 30–50-trade watchlist).
- **Fixed contradictions:** README (was "scalp engine", "live executor is a
  stub"; now multi-strategy + five-gate adapter truth, points to
  SYSTEM_STATE), ROADMAP (evidence-gate status updated: harness PASSED for
  donchian/squeeze, paper leg pending), LIVE_READY_CHECKLIST (§3 evidence
  table updated from "no strategy passes" to the real verdicts),
  DEPLOYMENT.md (removed accidentally duplicated "Parallel stacks" section,
  fixed "gated stub" wording, universe 12→17 per the expansion study),
  `.env.example` (documented donchian_trend + validated numbers, marked the
  retired scalp profiles, added STALE_ENTRY_GUARD_BARS), CLAUDE.md (current
  status now points at SYSTEM_STATE.md).

## Tests run

- `pytest`: **661 passed** (654 baseline + 7 new), nothing skipped/deleted.
- Offline `python main.py demo`: completes 40 cycles end-to-end, trades
  execute (synthetic exemption of the stale guard verified in practice).
- New stale-guard tests green.

## Docker commands checked

- `docker compose config` validates with `.env.example` copied to `.env`
  (compose OK). Container runtime not started in this sandbox (no Docker
  daemon); compose files unchanged this session except none.
- `scripts/start|stop|logs|health.sh` reviewed — correct, guard against
  missing `.env`, match DEPLOYMENT.md.

## Current system verdict

- **Paper: GO** — run the multi-strategy pairing on the 17-coin universe.
- **Live: BLOCKED** on paper evidence (30–50 trades), not on infrastructure.
- **Scalp: definitively dead** on this data/execution; the fast option is
  squeeze@1h + donchian@4h ≈ 4.5–5 trades/day.

## Current risk recommendation

`RISK_PCT=1.5`, `MAX_OPEN_TRADES=6`, exposure 200%, balance 200 USDT, kill
switch −10%/day, profit lock +10%/day (safer: 1.0%/4 slots). Do not raise
risk above the 3% band ceiling; do not touch parameters during the
evidence-collection window.

## Next actions (owner)

1. Deploy the `.env` from `FINAL_OWNER_DECISION.md` §6, fresh epoch.
2. Let it run; watch the §9 checklist for 30–50 trades. Change nothing.
3. Return with the numbers for the live decision.
4. (Optional engineering, separate wave) carry executor port — the only
   validated-but-unbuilt strategy.
