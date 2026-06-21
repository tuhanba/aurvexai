# Initial Build Report

**Project:** AurvexAI clean-core scalp engine
**Scope:** From-scratch rebuild — paper/shadow ready, live OFF.

---

## READY_FOR_PAPER: YES
## READY_FOR_LIVE: NO

The system runs end-to-end in paper mode: it pulls market data, scans a
universe, detects setups, scores, decides, opens/manages paper trades, tracks
shadows, logs the funnel, persists to SQLite, serves a dashboard on port 5000,
and can notify Telegram. Live trading is intentionally disabled: the live
executor is a gated stub that sends no real orders.

## Build at a glance

- **22** Python modules, **~3,460** LOC in `src/`.
- **10** test files, **55** tests, **all passing** (`pytest`).
- Verified offline: synthetic demo (60 cycles, trades opened/closed, balance
  ledger updated), all 9 dashboard endpoints return 200, backtester runs on
  2,000 bars × 4 symbols with a coherent metrics report.

## What was taken from the old `trade-engine` (as reference only)

- **Sane parameter values**: risk ~0.5%/trade, max open trades, leverage ceiling,
  per-coin cooldown, TP R-multiples, min stop distance, ADX≥18-ish trend gate,
  scalp-style threshold. Used as starting defaults, not copied code.
- **Setup vocabulary**: momentum breakout, liquidity sweep, volume expansion,
  trend continuation, extreme mean reversion — re-implemented cleanly.
- **Pipeline shape**: scanner → setup → score → risk → decision → executor, but
  collapsed into one linear, readable path.
- **Dashboard aesthetic**: gold/black, JetBrains Mono / Cinzel, dark theme.
- **Hard lessons**: schema/DDL drift, unreachable thresholds, missing event
  writes, dual-notifier duplication — explicitly avoided here.

## What was deliberately NOT carried over

- Friday CEO / autonomous narrative layer.
- Multi-AI consensus and any AI hard veto.
- Macro / news / sentiment / regime / reputation hard vetoes.
- ML and Ghost-learning **hard gates** (a lightweight observe-only shadow learner
  replaces them, advisory-only).
- Optuna auto-apply.
- Complex correlation veto and multi-branch duplicate veto chains.
- Redis and PostgreSQL (SQLite WAL is sufficient at this scale).

Rationale: the old engine's failure mode was complexity that made it impossible
to tell *why* a trade did or didn't happen, and impossible to trust. This build
optimises for one decision brain, explicit risk, and full observability.

## Why this architecture

- **One decision engine** shared by paper/live/backtest → provable parity, so
  paper results transfer to live.
- **Explicit arithmetic risk** → unit-testable, no hidden sizing.
- **Funnel observability** → every cycle records where signals died and the top
  reject reasons; "no trades" is always explained.
- **Simple infra** (SQLite, Flask, REST polling, CPU-only) → fewer moving parts,
  fast to deploy, easy to reason about; designed to grow (e.g. `tenant_id` later).

## Why Docker

The server already has Docker, and the user wants Docker-ready. Compose runs
engine + dashboard sharing one SQLite volume. Bare-metal (`python main.py …`)
also works for quick runs. CPU-only image (`python:3.12-slim`); no GPU needed.

## How to run

- Paper engine (real Binance public data, no key): `python main.py engine`
- Dashboard: `python main.py dashboard` → `http://<host>:5000`
- Offline demo (no network): `python main.py demo`
- Offline backtest: `python main.py backtest`
- Docker: `docker compose up -d --build`
- Full server/Termius steps: [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Tests — what passed

All 55 tests pass:

- `test_decision_engine.py` — ALLOW/WATCH/REJECT paths, filter rejects,
  determinism, decision contract fields.
- `test_paper_live_parity.py` — identical decision drives both executors; only
  execution differs.
- `test_risk_manager.py` — sizing math, guard bands, exposure cap, TP R-multiples
  (long & short), leverage cap.
- `test_paper_executor.py` — trade build, scale-out, breakeven move, pessimistic
  stop-before-TP, long/short PnL signs, fee accounting.
- `test_live_executor_mock.py` — readiness gate closed by default, human-confirm
  required, kill switch / connection / spread guards, stub-only `SIMULATED` send.
- `test_funnel_logger.py` — stage counting and top reject reasons.
- `test_shadow_learner.py` — tracking, TP/SL resolution (pessimistic), expiry,
  observe-first staging.
- `test_metrics_storage.py` — expectancy/PF/winrate/drawdown maths; SQLite
  round-trips for trades, balance ledger, funnel, signals.
- `test_backtest.py` — resample buckets, no-lookahead replay, coherent report.
- `test_market_data.py` — synthetic provider OHLC sanity/determinism/advance,
  ccxt provider builds without touching the network, pipeline fires setups.

## Tests / work remaining (future)

- Real ccxt order adapter for live (currently a stub) — Phase 4.
- Longer historical backtests against downloaded Binance klines (the offline
  generator is for harness validation, not edge proof).
- Optional websocket data path, Prometheus metrics, multi-tenant column.

## Why live mode is closed

No real-order code path exists by design. The live executor's `_send_order` is a
stub returning `SIMULATED`; the readiness gate is closed unless `LIVE_ENABLED`
and a human-confirm token are set. No Binance secret is read anywhere in paper
mode. This guarantees the build cannot place an order.

## Conditions required to go live (all must hold)

1. Positive, stable **expectancy** across paper, shadow and backtest with a
   meaningful sample per setup.
2. A real ccxt order adapter implemented behind the existing `LiveExecutor`
   interface (partial fills, timeout, retries, reconciliation, emergency stop).
3. Private Binance key provided via `.env` only (never committed).
4. `LIVE_ENABLED=true` **and** a `LIVE_HUMAN_CONFIRM` token set.
5. Start in **canary** mode (minimal size).
6. Parity tests still green (decision unchanged; only execution differs).
7. A separate, explicit go-live decision.

## First metrics to watch

Expectancy (R and USDT), profit factor, win-rate, average R, max drawdown,
TP1/SL hit rates — overall and broken down by setup, symbol, side and hour.
Plus funnel health: signals/day, top reject reasons, and time since last trade.
See [`RISK_MODEL.md`](RISK_MODEL.md) and [`ROADMAP.md`](ROADMAP.md).
