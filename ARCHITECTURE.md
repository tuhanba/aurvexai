# Architecture

## Design goals

1. **One decision brain.** Paper, live and backtest call the exact same
   `DecisionEngine.decide()`. No mode-specific strategy, threshold or veto.
2. **Explicit, testable risk.** Sizing is arithmetic you can read and unit-test.
3. **Observability first.** Every cycle records *why* nothing traded.
4. **Simple infrastructure.** SQLite, Flask, REST polling. No Redis, no Postgres,
   no websockets in the MVP. CPU-only, no GPU.
5. **Safe by construction.** No live orders; the live path is a gated stub.

## Pipeline

```
                       ┌──────────────────────────────────────────────┐
 market data provider  │  CCXTProvider (Binance public) | Synthetic    │
        │              └──────────────────────────────────────────────┘
        ▼
 UniverseScanner   → volume-ranked working set (exclude/size-bounded)
        ▼
 per symbol:
   get_snapshot     → MarketSnapshot {LTF candles, HTF candles, order book, funding}
   build_context    → cached indicators + HTF bias
   SetupDetector    → Signal (first matching setup, priority-ordered)
   ScoreBuilder     → score 0..100 (factors + book imbalance + spread tightness)
        ▼
 DecisionEngine.decide(signal, snapshot, portfolio):
   1) FilterChain   → 7 minimal hard filters (first failure wins)
   2) threshold     → ALLOW (≥ trade) | WATCH (≥ watch) | REJECT
   3) RiskManager   → sizing, guards, TP targets  (REJECT if no valid size)
   4) ALLOW         → Decision with full sizing
        ▼
 PaperExecutor.open → Trade (mode=paper)         [LiveExecutor is a gated stub]
        ▼
 TradeJournal       → persist trade + balance ledger
 simulate_fill      → manage open trades each bar (scale-out, BE, SL/TP)
 ShadowLearner      → track paper + high-score rejects; resolve TP/SL
 FunnelLogger       → per-cycle counts + top reject reasons
 Storage            → SQLite (WAL)
 Dashboard / Telegram (read / notify)
```

## Components

| Module | Responsibility |
|---|---|
| `config.py` | All tunables, env-driven. Paper and live share every value. |
| `models.py` | Plain dataclasses. `Decision` is the contract (`to_dict`/`to_json`). |
| `indicators.py` | Pure-python SMA/EMA/RSI/ATR/ADX/ROC — no numpy/pandas. |
| `market_data.py` | `CCXTProvider` (lazy ccxt, public data) and deterministic `SyntheticProvider`. |
| `scanner.py` | Ranks the universe by quote volume, applies include/exclude, bounds size. |
| `setups.py` | HTF `Context` + 5 detectors, each returns a `Signal` with factors. |
| `scoring.py` | Blends setup factors (70%) + base confidence (30%), book/spread nudges. |
| `filters.py` | 7 hard filters: daily-loss, max-open, duplicate, cooldown, liquidity, spread, slippage. |
| `risk.py` | Stop-distance guards, position sizing, leverage suggestion, TP targets. |
| `decision.py` | The single brain. Filters → threshold → risk → ALLOW/WATCH/REJECT. |
| `executors.py` | Shared `build_trade` + `simulate_fill`; `PaperExecutor`; gated `LiveExecutor` **stub**. |
| `storage.py` | SQLite WAL. Tables: trades, signal_events, funnel, shadows, heartbeat, balance_ledger, meta. |
| `metrics.py` | Expectancy (quote + R), profit factor, winrate, drawdown, breakdowns. |
| `journal.py` | Records trades and books realised PnL into the ledger (single source of balance truth). |
| `funnel.py` | Accumulates per-cycle observability counts. |
| `shadow.py` | Observe-first learner. Advisory only; never a hard veto. |
| `telegram.py` | Single notifier; `NullNotifier` when unconfigured. |
| `backtest.py` | No-lookahead replay through the same engine. |
| `engine.py` | Async loop tying it together; graceful shutdown; heartbeat. |
| `dashboard/` | Flask read-only API + auto-refreshing HTML. |

## Data flow & state

The engine is the only writer. The dashboard only reads. State lives in one
SQLite file (`DB_PATH`, default `data/aurvex.db`) in WAL mode so the dashboard
can read while the engine writes. Balance is a single value in `meta` plus an
append-only `balance_ledger`; the journal is the only place it changes, so
realised PnL and balance never drift.

## Why these infrastructure choices

- **SQLite over Postgres** — single-node, modest write rate, WAL gives concurrent
  reads. A `tenant_id` column can be added later for multi-tenant SaaS without a
  schema rewrite. No separate DB service to run.
- **Flask over FastAPI** — the dashboard is a handful of read-only JSON routes +
  one HTML page. No async server needed; fewer moving parts.
- **REST polling over websockets** — scalp cycle is ~20 s; polling Binance public
  REST (ccxt, rate-limited) is simpler and sufficient for the MVP. Websockets are
  a later optimisation if cycle latency matters.
- **No Redis** — there is no cross-process hot state to cache; SQLite covers it.
- **Pure-python indicators** — keeps the core import-light and trivially testable;
  no native build dependencies in the container.

## Concurrency / runtime

A single async loop processes one cycle at a time: scan → per-symbol decide →
manage open trades → resolve shadows → persist funnel + heartbeat → sleep. Each
per-symbol step is wrapped so one bad symbol can't abort a cycle. `SIGINT`/
`SIGTERM` set a stop event for a clean shutdown.
