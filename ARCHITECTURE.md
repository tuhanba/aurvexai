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
   build_context    → cached EMA/ADX/ATR/RSI + LTF Supertrend/Ichimoku/±DI + HTF bias
   SetupDetector    → Signal (active profile detector: bugra_replica | aurvex_enhanced)
   ScoreBuilder     → score 0..100 (per-setup factor weights + book imbalance + spread)
        ▼
 SetupDetector (Buğra 5-condition TA)  → PRIMARY ENTRY GATE (no signal → no trade)
        ▼
 DecisionEngine.decide(signal, snapshot, portfolio):
   1) FilterChain   → 8 minimal hard safety filters (first failure wins)
   2) score         → ADVISORY (no veto by default; SCORE_AS_GATE=false).
                      Optional opt-in soft floor MIN_EXECUTION_SCORE (default 0).
   3) RiskManager   → sizing, guards, TP targets  (REJECT if no valid size)
                      · risk_multiplier (support-side modulation, default 1.0)
   4) ALLOW         → executable candidate with full sizing
        ▼
 Score/Shadow SUPPORT (engine, never a veto):
   a) RANK    → order executable candidates by MEASURED edge; best win the
                max_open_trades slots (two-pass allocator, GLOBAL_RANKING=true).
   b) RISK    → modulate risk%/leverage/margin within hard caps, direction-
                validated (RISK_MODULATION_ENABLED, default off → neutral 1.0).
        ▼
 PaperExecutor.open → Trade (mode=paper)         [LiveExecutor is a gated stub]
        ▼
 TradeJournal       → persist trade + balance ledger
 simulate_fill      → manage open trades each bar (scale-out, BE, SL/TP)
 ShadowLearner      → track ALL executed + high-score rejects; resolve TP/SL
 FunnelLogger       → per-cycle counts + top reject reasons (+ ranked-out)
 Storage            → SQLite (WAL)
 Dashboard / Telegram (read / notify)
```

## Components

| Module | Responsibility |
|---|---|
| `config.py` | All tunables, env-driven. Paper and live share every value. |
| `models.py` | Plain dataclasses. `Decision` is the contract (`to_dict`/`to_json`). |
| `indicators.py` | Pure-python SMA/EMA/RSI/ATR/ADX/ROC + Supertrend/Ichimoku/±DI — no numpy/pandas. |
| `market_data.py` | `CCXTProvider` (lazy ccxt, public data) and deterministic `SyntheticProvider`. |
| `scanner.py` | Ranks the universe by quote volume, applies include/exclude, bounds size. |
| `setups.py` | `Context` (LTF Supertrend/Ichimoku/±DI cache + HTF bias) + 2 profile detectors (`bugra_replica`, `aurvex_enhanced`); legacy detectors removed. |
| `scoring.py` | Blends per-setup factor weights (70%) + base confidence (30%), book/spread nudges. `SETUP_WEIGHTS` must cover every active setup. |
| `filters.py` | 7 hard filters: daily-loss, max-open, duplicate, cooldown, liquidity, spread, slippage. |
| `risk.py` | Stop-distance guards, position sizing, leverage suggestion, TP targets. |
| `decision.py` | The single brain. Buğra signal → safety filters → (score advisory, no veto by default) → risk → ALLOW/REJECT. Score/Shadow rank + risk-modulate in the engine, never veto here. |
| `executors.py` | Shared `build_trade` + `simulate_fill`; `PaperExecutor`; gated `LiveExecutor` **stub**. |
| `storage.py` | SQLite WAL. Tables: trades, signal_events, funnel, shadows, heartbeat, balance_ledger, meta. |
| `metrics.py` | Expectancy (quote + R), profit factor, winrate, drawdown, breakdowns. |
| `journal.py` | Records trades and books realised PnL into the ledger (single source of balance truth). |
| `funnel.py` | Accumulates per-cycle observability counts. |
| `shadow.py` | Observe-first learner. Advisory only; never a hard veto. |
| `telegram.py` | Single notifier; `NullNotifier` when unconfigured. |
| `backtest.py` | No-lookahead replay through the same engine; 8h funding + runner-trailing inputs. |
| `walkforward.py` | Block 6 offline validation: segmented OOS walk-forward, funding, Monte-Carlo drawdown, deflated Sharpe, plateau check, decision table. |
| `engine.py` | Async loop tying it together; graceful shutdown; heartbeat. |
| `dashboard/` | Flask read-only API + auto-refreshing HTML. |

## Strategy profiles & validation

One detector runs per `STRATEGY_PROFILE`:

- `aurvex_enhanced` (default) — 5-condition TA core (EMA cross + Supertrend +
  Ichimoku + ADX/±DI) with a volatility-adaptive ATR stop.
- `bugra_replica` — the same TA core with a fixed-% stop/TP (Bugra replica).

Both feed the *same* `DecisionEngine` / `RiskManager` / executor (parity is
preserved). `SETUP_WEIGHTS` in `scoring.py` carries factor weights for both
active setups — without them every score is capped below `trade_threshold` and
nothing trades. Block 6 (`python main.py walkforward`) validates a profile
out-of-sample on real Binance data (deterministic synthetic fallback when
offline), net of fees + slippage + funding, and prints a per-profile decision
table. Live stays OFF until that table shows a positive net edge with an
acceptable drawdown (see `ROADMAP.md`).

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
