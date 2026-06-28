# AUDIT_FINDINGS.md — Phase 0 read-only audit

**Wave:** Edge Decomposition & Structural Execution Wave
**Phase:** 0 (read-only audit — HARD STOP GATE)
**Date:** 2026-06-28
**Scope:** verify the assumptions the wave rests on (execution model, AvgBars
meaning, funding, slippage, exits, lookahead, data availability). Change nothing.

> **Gate status:** this document is the Phase-0 deliverable. Per the task pack,
> Phase 1 must NOT start until these findings are reviewed. Two findings (F3,
> F6) materially change how the rest of the wave should be run — see
> **Recommendations** at the end.

---

## 0. Headline conclusions (read this first)

1. **The headline edge numbers (Exp-R, PF, MaxDD, Sharpe) are trustworthy.**
   They are computed from per-trade net PnL and are unaffected by the bugs below.
2. **`AvgBars` in the walk-forward table is a broken metric** (F3). It is *not*
   per-trade hold and *not* OOS sample length — it is an artifact of a
   wall-clock `close_time` stamp. The `~20016` figure does **not** prove the
   reversion exits are broken; it proves the metric is broken. This must be
   fixed before Phase 3 (exit replay) can interpret hold times at all.
3. **`reversion_v1` has a hard stop but NO time-stop** (F4). The reversion "one
   clean shot" in Phase 4 *requires* a time-stop that does not currently exist.
4. **This environment cannot run the real-data pipeline or the DB** (F6):
   no `data/` dir, no `data/aurvex.db`, no `data/cache/`, and outbound network
   to Binance (`fapi.binance.com`) is blocked. Phases 1–9 that need real
   candles or the SQLite ledger must run on the engine container / operator
   host, not here. Code-level work (model changes, tests) can still be done here.

---

## 1. Test suite — passing count

**Result: `487 passed` (floor is ≥403). PASS.**

```
PYTHONPATH=src python -m pytest
... 487 passed in 7.68s
```

**Caveat (environment, not code):** on the fresh clone the suite first showed
~16 failures, *all* `ModuleNotFoundError: No module named 'flask'` from the
dashboard tests. Installing `requirements.txt` (Flask etc.) resolved every one;
no code regression. No tests were skipped, xfailed, or modified.

---

## 2. Execution model used by `walkforward`

The walk-forward orchestrator (`run_walkforward_analysis`,
`walkforward.py:552`) replays each OOS window through `Backtester.run`
(`backtest.py:188`), which uses the **exact live pipeline**:
`build_context → SetupDetector → DecisionEngine → RiskManager →
PaperExecutor.simulate_fill`. There is no separate strategy logic — parity holds.

### Fills are TAKER (market) fills
Entries and exits realise through `BaseExecutor._close_fraction`
(`executors.py:118`). Cost is applied on **both** entry and exit notional:

```python
def _cost_frac(self):                     # executors.py:115
    return (self.cfg.taker_fee_pct + self.cfg.slippage_assumption_pct) / 100.0
cost = (entry_notional + exit_notional) * self._cost_frac()   # round-trip
```

There is **no maker code path**. `simulate_fill` fills TPs on touch
(`high >= tp.price`) and the stop pessimistically before TPs — all as taker.

### Fee constants
| Constant | Config field | Default | Source |
|---|---|---|---|
| Taker fee | `taker_fee_pct` | **0.045%** | `config.py:244`, `.env.example:115` |
| Slippage assumption | `slippage_assumption_pct` | **0.02%** | `config.py:245`, `.env.example:116` |
| Funding (8h) | `funding_rate_8h` | **0.0** (config) | `config.py:252`, `.env.example:119` |
| Max slippage (gate) | `max_slippage_pct` | 0.08% | `config.py:185` |

Round-trip cost = `(0.045 + 0.02) × 2 = 0.13%` — **matches the task pack's
"~0.13% round-trip" exactly.** Risk sizing already budgets this into 1R
(`risk.py:172`: `rt_cost_frac = (taker+slip)/100*2`), so a full stop realises
≈ −1.0R net, not −1.43R.

**Is a maker fee defined? NO.** Grep for `maker` finds only doc comments
("maker-friendly"). **Phase 4A must introduce a maker-fee constant** — there is
nothing to reuse.

### Funding — IS modeled (in walk-forward)
`funding_cost()` (`walkforward.py:171`) prorates the 8h rate over the bars held
and `Backtester._apply_funding` (`backtest.py:167`) charges it to both PnL and
balance. **Important nuance:**
- `run_walkforward_analysis` **forces** `funding_rate_8h = 0.0001` (0.01%/8h)
  via `dataclasses.replace` (`walkforward.py:579`) → walk-forward results **are
  net-of-funding**.
- The plain offline backtest uses the `Config` default `0.0` → funding **off**.
  Any offline backtest number is therefore *not* funding-adjusted; only the
  walk-forward table is.

Funding uses the **bar event timestamp** (`ts`) for hold length, not the buggy
`close_time` (see F3), so funding magnitude is correct.

### Slippage — modeled twice
1. **As a fixed cost** — `slippage_assumption_pct` (0.02%) folded into
   `_cost_frac`, applied every fill leg (above).
2. **As a pre-trade reject gate** — `f_slippage` (`filters.py:65`): estimates
   VWAP slippage to fill a conservative reference notional against the opposing
   book; rejects if `slip_pct > max_slippage_pct`.

**The "slippage = 216 rejects" gate is `f_slippage`.** In the backtest the
gate runs against an injected **synthetic tight book** (`_synthetic_book`,
`backtest.py:80` — 10 levels × 50 units, 2 bps spread) deliberately built so
microstructure guards pass and the test measures *strategy* edge. The 216 count
is the number of signals `f_slippage` rejected in that specific real-data run;
its `reject_reasons` are keyed by `failed_stage`/`reject_reason`
(`backtest.py:280`). **I could not reproduce the exact 216** here because the
run's cache and config are not present in this clone (F6) — but the gate is
unambiguously identified. (Note: with the synthetic book and small reference
notionals, `f_slippage` normally passes; a non-trivial reject count suggests the
reference notional exceeded synthetic book depth for that profile/balance, worth
confirming once the cache is available.)

---

## 3. `AvgBars` semantics — **BROKEN METRIC, flag loudly** (F3)

**Definitive answer from code:** `AvgBars` is *intended* to be **average
per-trade hold in bars**, NOT OOS sample length:

```python
avg_bars = sum(t.duration_bars for t in trades) / n         # walkforward.py:240
# duration_bars per trade:
dur_bars = round((close_t - open_t) / tf_ms)                # walkforward.py:520
```
The report header even comments it as "avg holding bars per trade"
(`walkforward.py:456`).

**But the input is corrupted.** Every TP/SL/BE close in `simulate_fill` stamps
the close with **wall-clock now**, not the bar timestamp:

```python
trade.close_time = now_ms()      # executors.py:260 (SL), :286 (TP) — WALL CLOCK
```
while `open_time` is the historical bar ts (`backtest.py:287`:
`trade.open_time = bar.ts`). So for any TP/SL/BE-closed trade:

```
duration_bars = (wall_clock_now − historical_entry_bar_ts) / tf_ms
```

— i.e. "how long ago the entry bar was," not how long the trade was held.
Only **force-closed** trades get the correct stamp (`backtest.py:296`:
`tr.close_time = last.ts`).

**Empirically demonstrated** (offline `bugra_replica`, 5m synthetic):

```
reason=TP3 open=...482724 close=...182790 close_is_nowish=True dur_bars=1359.0
reason=SL  open=...282729 close=...182794 close_is_nowish=True dur_bars=1423.0
reason=BE  open=...882724 close=...182803 close_is_nowish=True dur_bars=1191.0
avg_bars(reported semantics) = 744.25     # pure artifact of cache age
```

**Consequences:**
- The reversion `AvgBars ≈ 20016` is an **artifact of stale cache age**
  (≈ 20016 × 5m ≈ 69 days between entry bars and the run's wall clock), **not**
  evidence that reversion holds 20016 bars. The task pack's "if it's per-trade
  hold and ~20016 then exits are broken" trigger fires on a *broken metric* — so
  the proper conclusion is: **the metric can't be trusted to diagnose exits at
  all** until the stamp is fixed.
- **Crucially, the corruption is isolated to `avg_bars`.** Exp-R, PF, MaxDD,
  Sharpe, win%, and funding all derive from per-trade net PnL and bar-event
  timestamps — none read `trade.close_time`. **The edge verdicts in the
  walk-forward table are valid; only the hold-time column is junk.**

**Recommended fix (pre-Phase-3):** stamp `close_time` with the processed bar
timestamp in `simulate_fill` (the `bar_ts` already passed in), mirroring how
`force_close` uses `last.ts`. This is a behavior-neutral change for PnL but
makes hold-time and Phase-3 exit replay meaningful. **Not done in Phase 0**
(read-only gate); flagged for approval.

---

## 4. `reversion_v1` definition + hard stop / time-stop (F4)

**Detector:** `mean_reversion_setup` (`setups.py:325`). One detector per
profile (`_build_registry`, `setups.py:406`), so reversion never co-fires with
the Buğra momentum profiles.

**Entry rules (LONG; SHORT mirrors):**
- `entry < lower Bollinger band` (BB `rev_bb_n=20`, `rev_bb_k=2.0`) — stretched
- `LTF ADX < rev_adx_max (22)` — ranging, not trending
- HTF not strongly bearish (`htf_adx` None / `< rev_htf_adx_max` / `ema_fast ≥ ema_slow`)
- `LTF RSI < rev_rsi_long (30)` — oversold confirm

**Band construction:** `ind.bollinger(closes, 20, 2.0)` on **closed** LTF
closes (`setups.py:112`) → `{mid, upper, lower, std}`.

**Exits (`risk._build_targets`, `risk.py:336`):**
- **Hard stop: YES** — fixed `rev_sl_pct = 1.5%` from entry (`setups.py:383`).
- **Take-profit:** a **single** target at `rev_tp_r = 1.2R`, fraction **1.0**
  (TP2/TP3 are zero-fraction duplicates at the same price to keep the 3-slot
  contract). So it's effectively single-target, full-close.
- **No break-even move, no runner/trailing** (explicitly disabled for reversion).
- **Time-stop: NO.**

**Time-stop search across the whole codebase:** the only `*_max_bars` knob is
`shadow_max_bars` (`config.py:265`), used solely by the **shadow learner** to
resolve a shadow outcome (`shadow.py:219`) — it does **not** touch live/backtest
trade lifecycle. There is no `time_stop` / `max_hold` / `max_bars` exit anywhere
in `executors.py` or `backtest.py`.

**Implication for Phase 4's "reversion one clean shot":** the pre-committed
recipe is `reversion_v1 + hard stop + time-stop + maker entry`. The **hard stop
exists; the time-stop does NOT** and must be built. Until then, a reversion
trade that never reaches its single 1.2R TP or 1.5% SL rides until the window's
force-close — which (combined with F3) is exactly what inflated the reversion
`AvgBars`. This is consistent with "catastrophic tail / MaxDD 81%": no
time-stop means losers run to force-close.

---

## 5. No-lookahead confirmation — PASS

`build_context` (`setups.py:92`) uses **closed candles only**:
```python
ltf_candles = snap.closed_ltf(cfg.ltf)     # forming bar excluded
ctx.last = ltf.closes[-1]                   # last CLOSED close, not live tick
```
All indicators (EMA/ADX/RSI/ATR/Bollinger/Supertrend/Ichimoku/DI) are computed
on these closed series. Both `mean_reversion_setup` and the Buğra detectors key
off `ctx.last` (closed). HTF context is filtered `c.ts <= bar.ts`
(`backtest.py:247`). Entry-bar lookahead is structurally blocked: the trade
seeds `last_processed_bar_ts = entry_bar_ts` so the first fill can only occur on
a bar strictly after entry (`executors.py:70`, `:237`). **No lookahead found in
either `reversion_v1` or `bugra`.**

---

## 6. Cache / DB inventory & data availability (F6)

- **No `data/` directory exists** in this fresh clone → no `data/aurvex.db`
  (the read-only ledger Phase 1 needs) and no `data/cache/*.csv`.
- **Outbound network to Binance is blocked here.** `load_real_candles` for
  `BTC/USDT:USDT` 15m and 1h both failed:
  `ccxt fetch failed ... GET https://fapi.binance.com/fapi/v1/exchangeInfo`,
  returning 0 rows. So real candles cannot be pulled or cached from this
  environment.
- **The ≤1000-bar/call downloader fix IS in place:** `_paginate_ohlcv`
  (`walkforward.py:50`) pages forward by **timestamp** (`per_call=1000`), with
  the documented guard against terminating on a short-but-non-empty batch, and
  `load_or_fetch_candles` re-fetches on stale/short cache
  (`walkforward.py:111`). `_timeframe_ms` supports `m/h/d`, so 15m/1h/4h are
  structurally pullable wherever network exists.
- **Symbol-count discrepancy:** the task pack says "5 symbols," but the
  walk-forward default is **4** (`BTC/ETH/SOL/BNB`, `walkforward.py:576`).
  Confirm the intended symbol set with the operator before Phase 1.
- **DB read-only pattern already exists and matches the hard constraint:**
  `storage.py:285–290` opens `file:{path}?mode=ro` with `uri=True`, "no schema
  create, no migration, no PRAGMA writes." Tables present: `trades`, `funnel`,
  `shadows`.

**Consequence:** Phases 1–9 that require real candles (walk-forward, exit
replay, maker/HTF experiments) or the SQLite ledger **cannot be executed in this
Claude Code environment**. They need the engine container / operator host where
the cache and DB live. Code work (the F3 close_time fix, a maker-fill model, a
time-stop, new tests) *can* be authored and unit-tested here.

---

## 7. Guardrails honored in Phase 0
- Read-only: no source files changed; no DB opened for write; no migrations.
- `LIVE_ENABLED` untouched; no orders; no secrets read/printed.
- Only artifact added: this `AUDIT_FINDINGS.md`. Diagnostics ran in a scratch
  dir / via throwaway `python -c`, leaving no repo changes.

---

## 8. Recommendations / decisions needed before Phase 1

1. **[blocker] Where do Phases 1–9 run?** This env has no DB, no cache, and no
   Binance network (F6). Options: (a) operator runs the data-dependent phases on
   the engine container and shares `data/aurvex.db` + `data/cache/` back; (b) I
   author all code + unit tests here and the operator executes the measurement
   commands; (c) provide a network/proxy route to Binance for this env.
2. **[fix-first] Approve the `close_time` stamp fix (F3)** before Phase 3.
   Without it, every hold-time/exit-replay number is meaningless. It is
   PnL-neutral and additive to tests.
3. **[scope] Time-stop must be built (F4)** for reversion's Phase-4 "clean
   shot" — it does not exist today. Confirm this is in scope.
4. **[confirm] Symbol set:** 4 (code default) vs 5 (task pack)?
5. Note that **maker fee = 0 today** (F2) — Phase 4A starts from scratch and
   must use the *conservative* fill model the task pack mandates.

**Phase 0 is complete and is a hard gate. Awaiting review before Phase 1.**
