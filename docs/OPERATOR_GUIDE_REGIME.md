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

## 2. The one validated improvement — regime-adaptive allocation

Measured on real Binance 4h data (5.5y, 12 coins), out-of-sample (matrix fit on
H1, tested on the unseen H2) + a 5-fold walk-forward
(`docs/research/REGIME_ALLOCATION_OOS.md`):

- H2 Sharpe **1.79 → 1.96 (+10%)**, with **lower drawdown** (77.7 → 72.8 R).
- Walk-forward: regime+shadow beat flat in **4/5 folds**, mean ΔSharpe **+0.11**.
- Free — it reallocates risk within the existing book and the `[0.5,1.5]` band;
  it never raises per-trade risk above the half-Kelly 1.5%.

### How to enable it (owner decision; still paper, no live orders)
Add to `.env` and restart. These change SIZING only (never a gate, never a live
order):
```
REGIME_ENSEMBLE_ENABLED=true      # compute the multi-dim regime read
REGIME_EDGE_WEIGHT_ENABLED=true   # (already deployed) regime×edge risk tilt
REGIME_MATRIX_ENABLED=true        # use the measured (leg×regime) matrix weights
REGIME_DYNAMIC_RISK_ENABLED=true  # + confidence/transition de-risking
CORRELATION_CONTROLLER_ENABLED=true   # treat correlated same-side as one bet
DRIFT_MONITOR_ENABLED=true        # advisory leg-health state machine
REGIME_ALERTS_ENABLED=true        # Telegram on confirmed regime change
```
Optional (only ever TIGHTEN risk): `REGIME_DYNAMIC_SLOTS_ENABLED`,
`REGIME_DYNAMIC_EXPOSURE_ENABLED`, `MAX_NET_DIRECTIONAL_PCT`, `MM_TIERS_ENABLED`.
The measured matrix is `data/regime_matrix.json`; refresh it with
`python scripts/regime_matrix.py` after new data.

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

Nothing is missing. The system is clean, tested, and ready. The single validated
way to earn more from archived data is the regime lever above (+~10%
risk-adjusted, lower drawdown), enabled by config when you choose. The safety
gates that block bad trades stay in place — they are protecting the balance, not
obstructing it.
