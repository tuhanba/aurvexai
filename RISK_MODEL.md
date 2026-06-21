# Risk Model

Simple, explicit, and identical across paper, live and backtest. The same
`RiskManager` produces sizing for all three; there is no separate "live risk".

## Parameters (defaults, all in `.env`)

| Parameter | Default | Meaning |
|---|---|---|
| `INITIAL_PAPER_BALANCE` | 1000 USDT | Paper starting balance. |
| `RISK_PCT` | 0.5 | % of balance risked per trade (stop-out loss). |
| `MAX_OPEN_TRADES` | 4 | Concurrent open positions cap. |
| `MAX_DAILY_LOSS_PCT` | 3.0 | Daily realised-loss kill switch. |
| `MAX_LEVERAGE` | 10 | Upper bound on suggested leverage. |
| `MAX_PORTFOLIO_EXPOSURE_PCT` | 40 | Cap on total open notional vs balance. |
| `COIN_COOLDOWN_MINUTES` | 20 | Per-symbol cooldown after a trade. |
| `MIN_STOP_DIST_PCT` | 0.30 | Stops tighter than this are widened. |
| `MAX_STOP_DIST_PCT` | 2.50 | Stops wider than this are rejected. |
| `TP1_R` / `TP2_R` / `TP3_R` | 1.5 / 2.5 / 4.0 | Take-profit R multiples. |
| `TP1_FRAC` / `TP2_FRAC` / `TP3_FRAC` | 0.5 / 0.3 / 0.2 | Scale-out fractions. |
| `MAX_SPREAD_PCT` | 0.06 | Reject if book spread exceeds this. |
| `MAX_SLIPPAGE_PCT` | 0.08 | Reject if estimated fill slippage exceeds this. |
| `TAKER_FEE_PCT` | 0.045 | Per-side taker fee assumption. |
| `SLIPPAGE_ASSUMPTION_PCT` | 0.02 | Per-side slippage assumption. |

## Position sizing

Given an entry and a structure-based stop:

```
stop_dist_frac = |entry − stop| / entry
risk_amount    = balance × RISK_PCT/100
position_notional = risk_amount / stop_dist_frac
```

So a full stop-out loses ≈ `RISK_PCT` of balance, regardless of the coin or how
far the stop is. Example: balance 1000, risk 0.5%, 1% stop → risk_amount 5 →
notional 500.

### Guard band on the stop

- **Too tight** (`< MIN_STOP_DIST_PCT`): the stop is **widened** to the minimum
  so normal noise doesn't wick it out. (A tighter stop would also imply an
  unrealistically large notional.)
- **Too wide** (`> MAX_STOP_DIST_PCT`): the trade is **rejected** — scalp R/R
  would be poor.

### Exposure cap

```
max_total = balance × MAX_PORTFOLIO_EXPOSURE_PCT/100
room      = max_total − open_notional
```

If the computed notional exceeds `room`, it is clipped to `room`. If `room ≤ 0`,
the trade is rejected.

### Leverage suggestion

```
leverage = clamp(ceil(position_notional / balance), 1, MAX_LEVERAGE)
```

This is a *suggestion* surfaced in the decision; the paper engine does not borrow.

### Max loss estimate

```
max_loss = risk_amount + position_notional × (TAKER_FEE_PCT + SLIPPAGE_ASSUMPTION_PCT)/100 × 2
```

Round-trip fees + slippage are included so the figure is realistic.

## Take-profit construction

Targets are placed at `entry ± R×{1.5, 2.5, 4.0}` (sign by side) with scale-out
fractions 0.5 / 0.3 / 0.2. After TP1 the stop moves to breakeven. Fees and
slippage are deducted on **every** fill in `simulate_fill`, so realised PnL and R
multiples are net.

## Portfolio protections (hard filters)

Evaluated before sizing, first failure wins:

1. **Daily-loss kill switch** — if realised PnL for the UTC day ≤ −`MAX_DAILY_LOSS_PCT`
   of balance, all new entries are blocked.
2. **Max open trades** — blocks when `open_count ≥ MAX_OPEN_TRADES`.
3. **Duplicate** — one open position per symbol.
4. **Cooldown** — no re-entry within `COIN_COOLDOWN_MINUTES` of the last trade on
   that symbol.
5. **Liquidity** — minimum 24h quote volume.
6. **Spread** — reject if book spread > `MAX_SPREAD_PCT`.
7. **Slippage** — estimate VWAP fill of a conservative reference notional against
   the book; reject if > `MAX_SLIPPAGE_PCT`.

## Live-only safety (does NOT change the decision)

These live execution-safety mechanisms sit **downstream** of the decision and
only affect *whether/how an order is sent*, never the decision itself:

- **Readiness gate** — closed unless `LIVE_ENABLED=true` **and** a
  `LIVE_HUMAN_CONFIRM` token is set; also checks kill switch and connection.
- **Order-safety guards** — re-check spread/slippage at send time.
- **Canary mode** — `LIVE_CANARY_RISK_PCT` shrinks live position size on entries.
- **Kill switch / emergency stop** — blocks all sends.
- **Order timeout / retry limit** — `LIVE_ORDER_TIMEOUT_SEC`, `LIVE_MAX_RETRIES`.

In this build the order send is a **stub** that returns `SIMULATED` and never
contacts an exchange. See [`PAPER_LIVE_PARITY.md`](PAPER_LIVE_PARITY.md).

## North-star metric

**Expectancy** (per trade, in R and in quote currency) together with **profit
factor**, fee/slippage-inclusive. A strategy is only considered for live once it
shows positive expectancy across paper, shadow and backtest with a meaningful
sample. See [`ROADMAP.md`](ROADMAP.md).
