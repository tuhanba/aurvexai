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

---

# Wave 3 (2026-07-08): squeeze@4h frequency frontier + per-leg options

- Pre-registered cells (trials 95 → 99): squeeze@4h Q30 → **VALIDATED
  OPTION** (harness ACCEPTED: +0.161R, PF 1.43, DD 14%, DSR +2.82; +27%
  trades at ~85% yield). W12 killed (H2 t 1.0). squeeze@4h on 12 new coins
  → WATCH only (H2 +0.088R, t 0.89 — insignificant, NOT deployed).
  donchian N10/X20 reconfirmed (+12% trades, ~93% yield).
- Third consecutive measurement of the same law: more frequency costs
  per-trade edge; deployed baseline stays yield-optimal. "More action" now
  flips per leg via new STRATEGIES spec options `:n=` and `:q=`.
- Tests: **685 passed**. Docs: dossier §13, SYSTEM_STATE §7, .env.example.

---

# Wave 4-5 (2026-07-09): trend-TA inventory closed + Ichimoku port

- Popular trend-TA final wave (7 families @4h/1h): MACD/PSAR/band-ride pass
  raw split-half but the OVERLAP bar kills all three (50-86% same trades as
  deployed legs; non-overlap remainder has zero/negative holdout edge).
  Ichimoku@4h flagged WEAK -> owner directed a deep-dive.
- Ichimoku deep-dive (10 pre-registered cells, trials -> 121): **I1
  TK-cross strong @4h is the strongest harness result in the project** —
  net +0.314R, PF 1.71, DD 14.7%, DSR +4.14, 698 OOS trades, ACCEPTED;
  17/17 coins positive in the sim; H2 (2025+) +0.175R vs donchian's +0.03.
  All other 9 cells killed/weak.
- **Engine port shipped**: `ichimoku_trend` profile — detector, streaming
  TKCROSS exit (seeded pre-entry history at decide() time, parity across
  executors), risk branches, 7 tests. Deployed **SHADOW-ONLY**
  (`SHADOW_ONLY_SETUPS=ichimoku_trend`): zero risk, live evidence, ready
  as donchian's regime-substitute if the paper window confirms softness.
- Universe frontier re-check: squeeze@4h on the 10 phase-4-rejected coins
  KILLED (H2 -0.12R) — the 17-coin universe is the measured frontier.
- Tests: **692 passed**. Docs: dossier §13-addendum/§14/§15, SYSTEM_STATE,
  .env.example, FINAL_OWNER_DECISION.

---

# FINAL CONSOLIDATED REPORT — full session (2026-07-08 → 2026-07-09)

Eight waves, PRs #35–#38 merged to main. Campaign trial ledger 76 → 147.
Test floor 654 → **694 green**. Everything below is on real Binance USDT-M
archive data under the pre-registered protocol (no lookahead, full costs,
split-half/walk-forward, DSR deflation, kill-rule).

## Validated & deployed (the final system — FINAL_OWNER_DECISION §6/§10)

| leg | numbers (real harness) | role |
|---|---|---|
| donchian_trend@4h/1d ×17 | +0.284R, PF 1.37, DSR +2.44 (5.8y) | primary; 2025+ softness on watch |
| squeeze_breakout@1h/4h ×12 | +0.088R, PF 1.12, DSR +1.58 | fastest leg (24h holds) |
| squeeze_breakout@4h/1d ×17 (NEW) | +0.211R, PF 1.56, DD 9.5%, DSR +3.30 | best DD/DSR balance |
| ichimoku_trend@4h/1d ×17 (NEW, SHADOW-ONLY) | **+0.314R, PF 1.71, DSR +4.14** — best in book | zero-risk evidence collector; donchian substitute candidate |

Profiles: aggressive_paper (balanced, §6) and NEW **aggressive_plus** (§10:
risk 3%, 6 slots, profit lock 20%, kill switch fixed 10%) with the
validated more-action package (:n=10, :q=30). Per-leg spec options shipped:
:ts= :ch= :n= :q= :r= :u=.

## Killed with evidence this session (do not reopen without new data/infra)

Scalp (12 final families — structural NO-GO, 5 campaigns total); 34
additional coins across 3 edges (universe growth = dilution, 4×
confirmed); donchian@1d; squeeze@2h(W12)/looser variants; BTC-regime hard
filter; 7 popular trend-TA families (MACD/PSAR/BandRide pass split-half
but overlap analysis shows they ARE our trades); 9 of 10 Ichimoku
variants; EMA+Supertrend+Ichimoku composites (confluence = correlation,
not information); ALL 13 shorter-exit variants (yield −27…−85% — the edge
lives in multi-day winners).

## Engineering shipped (all tested, all merged)

ichimoku_trend profile (detector + streaming TKCROSS exit + risk
branches); same-profile-multi-TF; per-leg universe/params/risk; stale-data
entry guard; closed-bar kline cache + universe re-rank interval (~69→~18
REST calls/cycle); governor SHADOW_READINESS staircase; aggressive_plus
profile. Docs: SYSTEM_STATE (single truth), SCALP_EDGE_RESEARCH_REPORT,
SERVER_RUNBOOK, FINAL_OWNER_DECISION, dossier §9–§18.

## Honest growth outlook

Balanced (§6): ~0.3–0.45%/day expectation (~8–12%/mo). aggressive_plus
(§10): ~0.75–1%/day (~25–35%/mo) with 30–40% DD and losing weeks.
3–5%/day AVERAGE is unreachable with this edge — documented with the math.
Individual +3–6% days will occur (runner days at 3% risk).

## Queued next waves (owner to trigger)

1. **Pyramiding (turtle adds at +1R/+2R)** and **side asymmetry
   (long/short split per leg)** — the two genuinely untested classical
   accelerators; cheap pre-registered tests, sketched and ready.
2. **Carry engine port** — the only validated-but-unbuilt edge
   (+4–8%/yr uncorrelated; smooths portfolio DD → supports higher
   directional risk).
3. **The evidence window** — run the system 30–50 trades; then live
   decision + ichimoku/donchian comparison + sizing activation.

## Owner actions (one per line, Termius-safe)

    git pull
    nano .env        (paste §6 balanced or §10 aggressive_plus block)
    docker compose down
    docker volume rm aurvexai_aurvex-data
    docker compose up -d --build
    curl -fsS http://localhost:5000/health
