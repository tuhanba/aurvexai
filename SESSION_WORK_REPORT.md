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

---

# Wave 2 (same day, 2026-07-08): edge expansion + data speed + shadow

Owner directive: faster data flow, useful Shadow/Friday management, MORE
edge without diluting — "you are the system owner."

## Research (real archive data, pre-registered, kill-rule; trials 88 → 95)

- **NEW VALIDATED EDGE: squeeze_breakout @4h/1d (ts=24 = 96h)** — through
  the REAL walk-forward harness offline (archive data_override, deflated
  n_trials=95): net +0.193R / PF 1.49 / DD 15.5% / DSR +2.63 on the 5
  majors; net +0.211R / PF 1.56 / DD 9.5% / DSR +3.30 on the validated 17.
  Both split halves positive in the replication sim (+0.21/+0.18), 15/17
  coins. Deployed as the third strategy leg.
- **Killed honestly:** donchian on 12 new coins (H1 +0.63 → H2 −0.02 —
  coin-specificity confirmed again); squeeze@1h on expansion/new coins
  (negative — actionable: restrict squeeze@1h to its validated 12);
  donchian@1d (H2 ~0); BTC-SMA200 regime hard-filter (no H2 improvement,
  −46% trades → regime stays advisory). squeeze@2h = WATCH, not deployed.
- New combined validated frequency ceiling: **≈5.5–6 trades/day**.

## Code shipped (all tested)

1. **Same profile at two TFs** in STRATEGIES: spec keys, setup_type
   disambiguation ("squeeze_breakout@4h"), `models.profile_of()` for
   profile-semantics sites in risk/executors/decision.
2. **Per-strategy universe** `:u=BTC+ETH+...` — each edge trades only its
   validated coins.
3. **Closed-bar-aware kline cache** (`KLINE_CACHE_ENABLED`, default on) +
   **universe re-rank interval** (`UNIVERSE_REFRESH_SEC=600`): per-cycle
   REST calls ~69 → ~17–18 at the deployed config; order book stays live;
   failed refetch falls back to last good cache (stale-entry guard covers
   the tail). Parity-safe by construction.
4. **SHADOW_READINESS** governor section: explicit activation staircase
   (stage 1 SHADOW_APPLY ≥50 resolved/setup; stage 2 risk modulation needs
   N≥100 AND monotone buckets). Friday remains excluded by design; the
   governor report is its measured replacement.

## Tests

`pytest`: **684 passed** (661 → 684: +7 multi-TF/universe, +10 kline cache,
+6 shadow readiness). Offline demo end-to-end OK.

## Docs

SYSTEM_STATE.md §2/§6/§7/§8/§10/§11/§12, dossier §12, FINAL_OWNER_DECISION
(.env + monitoring), DEPLOYMENT.md (3-leg block), .env.example (u= + new
knobs). Research scripts archived: scripts/fetch_swing_klines.py,
scripts/edge_expansion.py, scripts/harness_sqz4h.py.
