# OPERATOR_GUIDE_REGIME.md — the owner's one-page "what's ready & how to run it"

**Date: 2026-07-24.** Consolidates the regime-adaptive work into a single
operator reference. Companion to `SYSTEM_STATE.md` (source of truth),
`LIVE_READY_CHECKLIST.md`, and `REGIME_ADAPTIVE_PORTFOLIO_IMPLEMENTATION.md`.

## 1. Status — everything is built, tested, and ready

- **All 8 phases implemented**, every decision-changing lever **flag-gated OFF by
  default**. With the flags off the engine is byte-identical to before (proven by
  `tests/test_regime_parity.py`).
- **Full suite green** (891 tests across 105 files). CI green.
- **Dashboard robust** — all 26 routes return cleanly on an empty/fresh DB (no
  data-flow 500s). Regime/drift/counterfactual read paths tolerate a missing
  table (fail-safe, never crash).
- **Live path clean + disarmed** — `python scripts/live_preflight.py` audits the
  five gates and prints exactly what is missing before any real order is possible.

## 2. RETRACTED — regime allocation is NOT a validated earn-more lever

**See `docs/research/REGIME_ALLOCATION_RETRACTION.md`.** An earlier version of
this guide claimed regime-weighted allocation was validated (+10% Sharpe) and
recommended `REGIME_MATRIX_TILT=1.5`. That result was measured on a silently
incomplete universe: a synthetic-order-book defect gave price-dependent depth, so
XRP/DOGE/ADA/TRX/TON produced ZERO backtest trades and the "12-coin" study was
really 7 coins.

Corrected (all 12 coins, 4,834 trades):

| | 7 coins (defective) | **12 coins (corrected)** |
|---|---|---|
| walk-forward ΔSharpe | +0.11 (4/5 folds) | **+0.01 (2/5 folds)** |
| tilt 1.5 | +0.31 (5/5) | **−0.02 (2/5)** |

Decisive reason: a regime cell's past edge does **not** predict its future edge
(pooled correlation **−0.051**); the cells mean-revert — the best-in-fit cells
regress DOWN in test. Per-regime differences are real descriptions of the past
with no forward information.

**Do NOT enable the matrix/tilt as an earn-more lever.** The regime stack stays
as OBSERVATIONAL infrastructure (monitoring, attribution, drift, alerts), which
is what it is good for.

## 3. Two measured dead-ends (do not re-chase)

- **Regime-gated mean-reversion:** net-negative in every regime, incl. chop
  (−0.10R after cost). Uncorrelated (−0.26) but negative expectancy kills it.
- **Volatility-targeting:** lowers Sharpe (this book earns in high vol); a
  drawdown tool, not an earn-more lever.

## 4. Telegram / Dashboard / Friday / Shadow — the observability stack

- **Telegram**: kill switch, daily profit target/lock, stop-approach, loss-budget,
  weekly report, hourly position digest, and now **confirmed regime-change alerts**
  (`REGIME_ALERTS_ENABLED`, hysteresis-gated so they're rare). `NullNotifier`
  when unconfigured — never crashes.
- **Dashboard**: `/api/regime` surfaces the live regime, flags, matrix, drift
  state and counterfactual uplift. Protect it with `DASHBOARD_AUTH_USER/PASS`
  before publishing port 5000 (HTTP Basic auth is built in).
- **Friday (governor)**: the read-only CEO report now unifies the advisory
  layers — shadow + the new `REGIME_ADVISORY` (regime, drift recommendations,
  counterfactuals) in one place. `python main.py report [--telegram]`. It stays
  **report-only**: `can_trade=false`, `READY_FOR_LIVE=NO`, always.
- **Shadow**: observe-first, never a veto; feeds the drift/counterfactual layers.

## 5. Going live — the deliberate, owner-only path (NOT automatic)

Real Binance orders are **off by construction** and stay off until the owner
opens the five-gate lock, gate by gate. This is intentional and load-bearing:
after the 2026-07-16 incident (engine ran 4h18m on a dead feed) the stale-feed
watchdog + entry guard block entries on genuinely stale data. **These are not
removed and must not be** — they are what protect real balance from trading on
prices that no longer exist.

To arm (owner action, deliberately):
1. `python scripts/live_preflight.py` — clear every listed blocker.
2. Trade-only (no-withdraw) Binance API key in `.env`.
3. `LIVE_ENABLED=true` + `LIVE_HUMAN_CONFIRM=<token>` + engine mode `live`
   (Telegram `/livemode confirm <token>` + restart) + `LIVE_SEND_ORDERS=true`.
4. Start in canary (`LIVE_CANARY_RISK_PCT`) with monitored first trades and a
   clean `reconcile()`.

The assistant will not flip these for you, default any on, or weaken the stale
guard — those are the owner's deliberate, reversible decisions and the system's
core money-safety.

## 6. Bottom line

The system is clean, tested and ready — but there is currently **no validated
earn-more lever** from archived data. Regime allocation was the candidate and it
did not survive the corrected measurement (§2). What remains true: the book's
existing edges are real, risk is correctly sized at half-Kelly, and the safety
gates protect the balance. The regime stack earns its keep as observability, not
as alpha.
