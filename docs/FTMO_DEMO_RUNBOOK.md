# FTMO demo paper-forward runbook

The offline research is done: the gold-ORB + DAX/NAS100-PDHL portfolio passes FTMO
in the governed backtest and holds up 5/5 out-of-sample folds (`FTMO_STATE.md`).
The **one** thing offline cannot settle is **live breakout stop-entry slippage**.
This runbook is how you settle it on a real FTMO demo — and the repo already has
the tooling to turn your demo fills into an automatic GO/NO-GO.

> ⚠️ There is **no auto-execution adapter** to FTMO/MT5 yet (a separate,
> credential-dependent wave). This runbook is the **manual / semi-manual** path:
> the engine tells you the exact orders; you place them on the demo; the repo
> scores your fills. Nothing here connects to a broker automatically.

## 0. Prerequisites

- An **FTMO Free Trial** or a demo account on their platform (MT4/MT5/cTrader).
- The three instruments available: **XAUUSD** (gold), **GER40** (DAX), **NAS100**.
- This repo checked out; `pip install -r requirements.txt`.

## 1. Each trading day — get the order levels

```
python scripts/ftmo_signals_today.py
```

It fetches fresh 1h data and prints, for the current session:

- **XAUUSD (ORB):** buy-stop at the first-hour HIGH, sell-stop at the first-hour
  LOW, stop = opposite side of that range.
- **GER40 / NAS100 (PDHL):** buy-stop at the prior day's HIGH, sell-stop at the
  prior day's LOW, stop = 1.5 × ATR(14).

## 2. Place the orders on the demo

For each instrument, place **both** pending **stop-entry** orders at the printed
levels with the printed stop-loss. Rules that matter for the edge:

- **First break wins:** once one side triggers, cancel the other for that
  instrument/session.
- **Risk 0.5%** of the account per trade (position size = 0.5% ÷ stop distance).
- **Exit at the session close** (flat by 00:00 UTC) — set a time-based close or do
  it manually. No fixed profit target on the ORB session-close variant.
- Respect the FTMO daily/overall loss budget — if a rule is close, skip.

## 3. Record every fill

Keep a CSV with this exact header (one row per trade):

```
instrument,side,signal_level,fill_price,exit_intended,exit_fill
XAUUSD,LONG,3300.0,3300.9,3333.0,3332.4
GER40,SHORT,20000.0,19996.0,19800.0,19803.0
```

- `signal_level` = the level the strategy meant to enter at (the stop-order price).
- `fill_price` = the price you **actually** got (the slippage lives here).
- `exit_intended` / `exit_fill` = intended vs actual exit (blank exit_fill ⇒ = intended).

## 4. Weekly — score your fills → GO/NO-GO

```
FTMO_FILLS_CSV=my_demo_fills.csv python scripts/ftmo_slippage_check.py
```

It computes the **realised per-instrument round-trip cost** (entry + exit
slippage) and **re-runs each edge's governed backtest at that measured cost**,
printing a per-instrument **GO / NO-GO**:

- median realised round-trip cost ≤ **0.06%** → within budget;
- and the edge still governed-passes at that cost → **GO**.

## 5. Decision criteria (when to trust it)

- Collect **≥ 20–30 trades per instrument** before believing the slippage number
  (a handful of fills is noise).
- **GO** for an instrument = realised cost within budget **and** the edge passes at
  that cost. Trade only the GO instruments.
- If **no** instrument clears the budget, the live cost kills the edge — an honest
  **NO-GO**. The OS + lab are then ready for the next edge (`scripts/ftmo_edge_search*`).

## 6. Only after a clean demo

Consider a funded attempt **only** when: several weeks of demo fills show the
instruments are GO, per-challenge-window drawdown stays < 10% (it did in
backtest — 5.7–7.9% per fold), and you've re-verified the FTMO rules for your
exact account type. Then run the paper engine with governance as a live shadow:

```
FTMO_MODE_ENABLED=true STRATEGY_PROFILE=orb ORB_HOURS=1 ORB_TARGET_R=0 python main.py engine
```

## What the repo gives you vs what only you can do

| Step | Tool | Who |
|---|---|---|
| Daily order levels | `ftmo_signals_today.py` | repo ✅ |
| Placing the orders on the demo | your FTMO/MT5 platform | **you** |
| Recording fills | a CSV | **you** |
| Realised cost + GO/NO-GO | `ftmo_slippage_check.py` | repo ✅ |
| Edge re-run at your measured cost | governed backtester | repo ✅ |

The measurement is turnkey; the only thing that needs a human + a broker is
placing the trades and recording the fills.

## Demo toolkit — all the helpers

| Helper | What it does |
|---|---|
| `scripts/ftmo_signals_today.py` | Today's ORB/PDHL order tickets **with lot sizing** (entry, stop, ~lots). |
| `scripts/ftmo_send_signals.py` | Same tickets **pushed to Telegram** — run as a daily cron after 01:00 UTC. |
| `scripts/ftmo_recent_trades.py` | **Dry run:** what the edges actually did in the last ~45 sessions on real data. |
| `scripts/ftmo_verify_ppv.py` | Back out your broker's true contract value (PPV) from one closed trade. |
| `scripts/ftmo_slippage_check.py` | Turn your recorded fills into a per-instrument **GO/NO-GO**. |
| `docs/ftmo_fills_template.csv` | The fills CSV template to copy. |

**Daily Telegram cron** (levels on your phone every weekday after the gold first
hour closes):

```
5 1 * * 1-5  cd /path/to/aurvexai && PYTHONPATH=src FTMO_ACCOUNT_SIZE=100000 \
  FTMO_GER40_PPV=25 FTMO_NAS100_PPV=20 python scripts/ftmo_send_signals.py
```
(Requires `TELEGRAM_ENABLED=true` + `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in
`.env`; without them it just prints.)

**Verify your index contract sizes first** — indices vary by broker and a wrong
PPV mis-sizes every trade. After one closed index trade:
`python scripts/ftmo_verify_ppv.py <entry> <exit> <lots> <realised_pnl>` → set the
printed value as `FTMO_GER40_PPV` / `FTMO_NAS100_PPV`.

## Auto-execution (later, disarmed)

`src/aurvex/ftmo/mt5_adapter.py` is the future MT5 order path. It is **disarmed**:
a simulated stub unless `FTMO_LIVE_EXECUTE=true` **and** MT5 credentials **and**
`FTMO_MT5_HUMAN_CONFIRM=I_UNDERSTAND` **and** the `MetaTrader5` package are all
present (mirrors the Binance five-gate lock). Do not arm it until the demo
GO/NO-GO is GO, and even then run it on the demo first. The real `order_send` path
is a reviewed skeleton, not yet executed against a live terminal.
