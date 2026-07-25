# REGIME_SCALP_WAVE.md — does regime/volatility conditioning rescue scalp? NO.

**Date: 2026-07-24.** Owner request: "let's do hit-and-run (vur-kaç), condition it
on regime and volatility, and test it." Done — and this is the largest scalp test
in the project's history. Harness: `scripts/regime_scalp_wave.py`. Data: real
Binance 15m archive klines, 12 coins, 30 months (~87.5k bars/coin).

## Result: 222,490 trades, 30 cells, ZERO net-positive

3 families (momentum breakout, mean reversion, range break) × 10 conditions
(7 macro regimes from the BTC-4h ensemble + 3 volatility states). Conservative
fills (next-open entry, stop-first), cost = 0.13% taker round trip charged in R
against the actual stop distance.

| | range across all 30 cells |
|---|---|
| GROSS R (before cost) | −0.085 … **+0.046** |
| cost (R) | 0.105 … 0.318 |
| NET R (after cost) | **−0.105 … −0.312** |

**Not one cell is net-positive.** The best conditioned cell (RB rangebreak @
VOL_HIGH): gross **+0.046R**, cost **0.177R**, net **−0.131R** — cost is ~4× the
edge. This is the structural finding from the six prior campaigns, now confirmed
*with* regime AND volatility conditioning at 222k trades.

## The diagnostic that matters (gross vs net, split deliberately)

Splitting gross from net answers "is there no signal, or is there signal that
cost eats?" The answer is **both, but mostly the first**: gross edge is ≈0
everywhere (best +0.046R), so there is very little to protect even before cost.
A filter cannot create edge — it only selects a subset of the same trades — so
conditioning was never able to rescue this, and now that is measured rather than
assumed.

## The constructive signal in the data

Cost is LOWEST exactly where volatility is highest — PANIC (0.105–0.140R) and
VOL_HIGH (0.169–0.177R) — because a wide ATR means a wide stop, and cost measured
in R shrinks as the stop widens. Gross edge is also (mildly) best there.

Extrapolating: for cost to fall below the best observed gross edge (+0.046R), the
stop would have to be roughly **4× wider than a scalp stop** — which is a *swing*
stop. **The arithmetic points at the system that already exists**: donchian's
2×ATR stop and the 4h legs work not because they are slow, but because their stop
distance clears the cost bar.

## Conclusion for the owner

"Hit-and-run" is not a tunable preference — it is an identity: small stop ⇒ high
cost per trade in R. 222,490 trades across 30 regime/volatility conditions say
that identity loses after cost, every time.

The safe route to more trades remains **more independent edges that clear the
cost bar** (other coins/timeframes, or an uncorrelated stream such as carry), not
faster hit-and-run. Scalp stays closed; this campaign closes the
regime/volatility-conditioned variant specifically.
