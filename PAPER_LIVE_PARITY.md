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
market data → scanner → Buğra setups [primary gate] → safety filters
            → (score advisory, no veto) → risk
            → DecisionEngine.decide(signal, snap, pf, risk_multiplier)
            →  Decision   ◄── identical for paper, live & backtest
```

There is exactly **one** `DecisionEngine`, **one** `trade_threshold`, **one**
`RiskManager`. No live-only scoring, no live-only veto chain, no live-only
threshold. The backtester uses the same `decide()` too.

**Buğra primary gate (2026-06-25).** Two shared-path additions, both mode-agnostic:
- The score veto is OFF by default (`SCORE_AS_GATE=false`); score is advisory. The
  same flag/branch lives in the shared `decide()`, so paper/live/backtest behave
  identically. Score/Shadow act only as a **support** layer in the engine (ranking
  + risk modulation) — they never branch on mode.
- `decide()` gained a `risk_multiplier` argument (default `1.0` → byte-identical
  sizing) passed straight into the shared `RiskManager.evaluate`. The engine
  computes it from **measured** edge once per cycle and feeds the same value
  through the same brain regardless of executor, so parity holds. It scales the
  risk budget only, within every existing cap and the liq-safety invariant.

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
- **Block 4 exit model (shared).** TP1 → cost-adjusted break-even, TP2 → stop
  locked to the TP1 price, TP3 → runner trailing (when `RUNNER_FRAC>0`), and the
  monotone trailing ratchet all live in the shared `simulate_fill`, so paper,
  live-mock and backtest exit identically. The shadow research replay
  (`ShadowLearner.ladder_replay`) mirrors the same exit logic (cost-BE, TP1-lock,
  ATR-trailed runner booked at its real exit price) so shadow expectancy does not
  drift from the paper executor. Still advisory only — never a veto.

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

## squeeze_breakout profile (2026-07-05) — parity reasoning

The edge-search candidate was added as a fourth strategy profile. Parity
holds by the same construction as reversion_v1:

- New detector (`detect_squeeze_breakout`) is pure Context→Signal; registry
  isolation means it ONLY runs under `STRATEGY_PROFILE=squeeze_breakout`,
  and no other profile's behavior changes (631 tests green, all prior
  suites untouched).
- `normalize_stop` gained a squeeze-specific ceiling (`MAX_STOP_DIST_PCT_SQZ`)
  and `_build_targets` a no-TP branch (single unreachable target keeps the
  3-slot contract) — both keyed on setup_type/profile, mode-agnostic, and
  identical across paper/live/backtest.
- Exit uses the existing TIME_STOP_BARS mechanism (executor-level, mode-
  agnostic). `decide()` itself is unchanged.

## Going live (Stage 3 — built 2026-07-03, disarmed by default)

The real order adapter now exists (`live_orders.py`), wired as an
**executor-only** concern — parity is untouched by construction:

- `DecisionEngine.decide()` was not modified; the same Decision object feeds
  paper and live. Sizing/threshold/risk logic identical.
- `LiveExecutor._send_order()` without an armed adapter is byte-for-byte the
  old SIMULATED stub. With an armed adapter it delegates the SAME decision
  (canary-scaled notional only) to `LiveOrderAdapter.send_entry()`.
- Arming requires the five-gate lock: `LIVE_ENABLED` + `LIVE_HUMAN_CONFIRM`
  + live mode (Telegram confirm + restart) + `LIVE_SEND_ORDERS=true` + keys.
  Every default is off. `tests/test_stage3_live_orders.py` proves each gate
  is individually sufficient to keep it disarmed.
- A refused/failed live send opens NO trade (the engine skips the slot);
  it never mutates the decision or re-enters the decision path.

Still required before arming for real: a positive-expectancy track record
(currently NO-GO — see `PAPER_PERFORMANCE_REPORT.md`), a trade-only key, and
canary sizing. Until then the system stays in paper and places no real
orders.
