# AurvexAI — Clean-Core Scalp Engine

A from-scratch, deliberately simple crypto-futures **scalp** engine for Binance
USDT-M perpetuals. One decision brain, explicit risk, paper/live parity, shadow
learning, funnel observability, a basic dashboard and Telegram alerts.

> **Live trading is OFF.** This build sends **no real orders**. The live
> executor is a gated **stub**. Going live requires a separate, explicit
> decision and a code change. See [`PAPER_LIVE_PARITY.md`](PAPER_LIVE_PARITY.md)
> and [`RISK_MODEL.md`](RISK_MODEL.md).

---

## What it does

```
market data → universe scanner → setup detector → score builder
            → minimal filters → risk manager → CORE DECISION ENGINE
            → paper executor (paper trade journal)
            → shadow learner  → dashboard API → Telegram
```

The **same** core decision engine is used by paper, live and the backtester.
Only the executor downstream differs.

## Quickstart (local)

```
pip install -r requirements.txt
cp .env.example .env
```

Run an offline, no-network synthetic demo (proves the whole pipeline):

```
python main.py demo
```

Run an offline backtest (seeded synthetic data, fees/slippage included):

```
python main.py backtest
```

Run the real paper engine against Binance **public** data (no API key needed):

```
python main.py engine
```

Run the dashboard (defaults to port 5000):

```
python main.py dashboard
```

Then open `http://localhost:5000`.

## Quickstart (Docker)

```
cp .env.example .env
docker compose up -d --build
```

Engine + dashboard come up sharing one SQLite volume. Dashboard on `:5000`.
Full server/Termius instructions are in [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Operations (Docker)

Run from the project root (helper scripts wrap the same `docker compose` calls):

| Action | Command |
| --- | --- |
| Start (build + run) | `docker compose up -d --build`  ·  `bash scripts/start.sh` |
| Stop (keep data) | `docker compose down`  ·  `bash scripts/stop.sh` |
| Status | `docker compose ps` |
| Logs (all / one) | `docker compose logs -f --tail=200 [engine\|dashboard]`  ·  `bash scripts/logs.sh [engine\|dashboard]` |
| Health check | `curl -fsS http://localhost:5000/health`  ·  `bash scripts/health.sh` |
| Update to latest | `git pull` → `docker compose up -d --build` |
| Wipe paper history | `docker compose down` → `docker volume rm aurvexai_aurvex-data` |

The `aurvex-data` volume (SQLite WAL) persists across `down`/up and restarts.
Containers use `restart: unless-stopped`, so they survive reboots.

## Configuration

All settings come from environment variables / `.env`. See
[`.env.example`](.env.example) for every knob with comments. **Secrets
(Binance keys, Telegram token) live only in `.env`, never in code.** Paper mode
needs no Binance key at all — Binance public market data is enough.

Key defaults: paper balance **1000 USDT**, risk **0.5%/trade**, max **4** open
trades, daily-loss kill switch **3%**, trade threshold **60**, LTF **1m** /
HTF **15m**.

## Project layout

```
src/aurvex/
  config.py        # all tunables, env-driven
  models.py        # dataclasses (Candle, Signal, Decision, Trade, FunnelStats…)
  indicators.py    # pure-python EMA/RSI/ATR/ADX…
  market_data.py   # ccxt (public) + synthetic providers
  scanner.py       # volume-ranked universe
  setups.py        # 5 scalp setup detectors + HTF context
  scoring.py       # 0–100 net score
  filters.py       # 7 minimal hard filters
  risk.py          # sizing, guards, TP construction
  decision.py      # THE single decision brain
  executors.py     # shared fill sim; PaperExecutor + gated LiveExecutor STUB
  storage.py       # SQLite (WAL)
  metrics.py       # expectancy, PF, winrate, drawdown, breakdowns
  journal.py       # trade recording + balance ledger
  funnel.py        # per-cycle observability
  shadow.py        # observe-first shadow learner
  telegram.py      # notifier (+ NullNotifier)
  backtest.py      # no-lookahead replay (same engine)
  engine.py        # async runner loop
  dashboard/       # Flask app + HTML
main.py            # engine | dashboard | demo | backtest
tests/             # 55 tests
```

## Tests

```
pytest
```

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — components and data flow
- [`SCALP_STRATEGY_SPEC.md`](SCALP_STRATEGY_SPEC.md) — the 5 setups in detail
- [`RISK_MODEL.md`](RISK_MODEL.md) — sizing and protection
- [`PAPER_LIVE_PARITY.md`](PAPER_LIVE_PARITY.md) — the core invariant
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — server / Docker / Termius
- [`ROADMAP.md`](ROADMAP.md) — what comes next
- [`INITIAL_BUILD_REPORT.md`](INITIAL_BUILD_REPORT.md) — build decisions + readiness
