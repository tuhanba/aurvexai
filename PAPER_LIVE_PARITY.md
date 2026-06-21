# Paper / Live Parity

## The invariant

> The **same** mock signal produces the **same** `Decision` in paper and live.
> Score, threshold, filters and risk sizing are identical. The only thing that
> differs is the **executor**.

This is the most important property in the system. It means anything proven in
paper (scanner, setups, scoring, filters, threshold, risk, SL/TP, cooldown,
max-open, duplicate handling, the decision logic) carries over to live unchanged.

## What is shared

Everything up to and including the decision:

```
market data → scanner → setups → scoring → filters → threshold → risk
            → DecisionEngine.decide()  →  Decision   ◄── identical for paper & live
```

There is exactly **one** `DecisionEngine`, **one** `trade_threshold`, **one**
`RiskManager`. No live-only scoring, no live-only veto chain, no live-only
threshold. The backtester uses the same `decide()` too.

### Wave 1 integrity changes (still on the shared path)

These fixes harden the shared decision/fill path; none introduces a paper-only
or live-only branch, so parity is preserved:

- **Closed-candle view (T1).** Signals, scoring, open-trade management and shadow
  resolution consume `MarketSnapshot.closed_ltf()` — closed bars only — so no
  mode can act on the forming bar. `last_price` stays live for execution realism.
- **Entry-bar / one-fill timing (T2).** `entry_bar_ts` travels on the `Decision`;
  `simulate_fill(bar_ts=...)` (shared) fills only on closed bars strictly after
  entry, once per bar. Same code for paper, live-mock and backtest.
- **Cost-inclusive sizing (T4).** `RiskManager` sizes notional on
  `stop_dist + round-trip cost`, so 1R is the net budget and a full stop is
  ~-1.0R. Computed once in the shared risk model.
- **Slot-aware leverage (T5).** Leverage is chosen from a slot-aware target
  margin in the shared `RiskManager`; it changes only margin/liquidation
  distance, never notional, risk, or the decision. Canary still scales live
  notional and margin in the same ratio.
- **Shadow stop normalisation (T3).** The shadow learner reuses the engine's
  `normalize_stop()` so its proxy is measured against the exact stop the engine
  would trade — advisory only, never a veto.

## What differs (executor only)

| | Paper | Live (this build) |
|---|---|---|
| Class | `PaperExecutor` | `LiveExecutor` (**stub**) |
| Order send | Writes a virtual trade to SQLite | `_send_order()` returns `SIMULATED`; **no exchange call** |
| Readiness gate | n/a | Closed unless `LIVE_ENABLED=true` **and** `LIVE_HUMAN_CONFIRM` set |
| Order-safety guards | n/a | Spread/slippage re-check at send time |
| Canary risk | n/a | `LIVE_CANARY_RISK_PCT` shrinks position size |
| Fill model | Shared `simulate_fill` | Shared `simulate_fill` |

The live executor **consumes** the decision; it never alters entry, stop, TP
prices, score, threshold or risk %. It may only (a) refuse to act (gate/guards),
or (b) scale the position smaller (canary). Both are execution concerns.

## How it is enforced

- `DecisionEngine.decide()` takes no `mode` argument and has no mode branches.
- `BaseExecutor.build_trade()` is shared; `PaperExecutor` and `LiveExecutor`
  both call it with the identical `Decision`.
- `LiveExecutor._send_order()` is a stub returning
  `{"status": "SIMULATED", "note": "stub - no real order placed"}`.

## How it is tested

`tests/test_paper_live_parity.py`:
- Builds one `Decision`, feeds a deep copy to both executors, asserts the
  resulting trades share entry, stop, TP prices, score, threshold, risk %, and
  leverage; only `mode`, `position_size` (canary) and the `simulated` flag
  differ.
- Asserts the decision path does not branch on mode (same threshold/decision).

`tests/test_live_executor_mock.py`:
- Gate is **closed by default** (`LIVE_ENABLED=false`).
- Requires a human-confirm token even when enabled.
- Kill switch, connection failure, spread guard each block.
- `_send_order` returns `SIMULATED` — proof no real order is ever placed.

## Going live (future, explicit)

Out of scope for this build and intentionally not wired. It would require:
1. An explicit decision to enable it.
2. Replacing `_send_order()` with a real ccxt order adapter (private API key in
   `.env` only) — partial-fill handling, order timeout, retries, reconciliation.
3. Setting `LIVE_ENABLED=true` and a `LIVE_HUMAN_CONFIRM` token.
4. Starting in canary mode with minimal size.
5. A positive-expectancy track record from paper/shadow/backtest first.

Until all of that, the system stays in paper mode and places no real orders.
