# TREND_FAMILY_BATTERY.md — Supertrend & friends: the untested members of the family that works

**Date: 2026-07-24.** Owner: *"must it be these TAs? Supertrend, Fibonacci,
why aren't we trying the others?"* Fair question. Inventory first, then the gap.

## Already covered (so the question is narrower than it looks)

- `classic_ta_battery.py` — 14 textbook indicators: RSI/Stochastic/CCI/
  Williams %R/Bollinger mean-reversion, RSI-momentum, MACD, ROC,
  Stochastic-momentum, EMA 9/21, EMA 21/50, ADX+DI, Donchian, Price>EMA50.
- `fib_test.py` — **Fibonacci retracement: NO-GO.** The classic 0.5/0.618/0.786
  levels are systematically negative; the deeper the retrace the worse.
- Earlier campaigns: ICT/SMC (FVG, order blocks, liquidity sweeps), squeeze,
  band-walk, Ichimoku, and a ~40-feature gradient-boosted ML combination.

**The real gap: Supertrend had never been tested standalone** — it existed only
as one component inside the retired `aurvex_enhanced` profile.

## Where to look (the data chose the direction, not us)

The classic battery's own conclusion: oscillators and mean-reversion lose after
cost, momentum clusters near zero, **only the trend/breakout family survives**.
So the highest-probability untested ground is the rest of THAT family.

## Results — `scripts/trend_family_battery.py` (4h, 11 coins, net of 0.13% RT, R vs 2×ATR, H=6)

| signal | n | netExpR | t |
|---|---|---|---|
| **Keltner breakout** | 15,249 | **+0.0427** | **+4.48** |
| Chandelier / ATR channel | 128,020 | −0.0041 | −1.52 |
| **Supertrend(7,2)** | 131,646 | **−0.0051** | −1.91 |
| **Supertrend(10,3)** | 131,646 | **−0.0070** | −2.63 |
| LinReg slope(20) | 131,646 | −0.0090 | −3.37 |
| Vortex(14) | 131,646 | −0.0096 | −3.57 |
| Hull MA(20) | 131,646 | −0.0185 | −6.89 |
| Heikin-Ashi trend | 131,646 | −0.0218 | −8.14 |
| Parabolic SAR | 131,646 | −0.0227 | −8.46 |
| Aroon(25) | 131,646 | −0.0466 | −17.37 |

**Supertrend is a NO-GO** at both common parameterisations — the owner's specific
ask is now measured rather than assumed. Nine of ten are negative.

## The one positive cell — and why it is still not a new leg

Keltner is the only positive, and the reference matters: in this SAME crude
framework the DEPLOYED `Donchian breakout(20)` scores **−0.0004**. The crude
harness (fixed 6-bar hold, no stop, no exit rule) massively understates a real
strategy — donchian measures **+0.357** in the actual engine. So Keltner beating
donchian here is a genuine signal, and it survived a proper re-test:

**Keltner with real mechanics** (2×ATR stop, 24-bar max hold, edge-triggered,
non-overlapping): **n=2,820 · netExpR +0.1405 · t +4.08 · H1 +0.182 / H2 +0.099
(both halves positive)** — the same level as the deployed squeeze@4h (+0.146).

**But it is not independent.** Signal-overlap vs donchian:

| | |
|---|---|
| Keltner signals | 5,011 |
| Donchian signals | 8,570 |
| same (symbol, bar, direction) | 2,869 = **57.3%** |
| within ±2 bars | **82.3%** |

Keltner is essentially a *filtered donchian* — it fires on the same breakouts,
selecting those that are also ≥2×ATR extended from the EMA. Adding it as a fifth
leg would be **double-sizing one bet, not adding an edge**, exactly the reason
`ichimoku@8h` was not adopted.

## Verdict

- **Supertrend, Parabolic SAR, Aroon, Vortex, Hull MA, LinReg slope,
  Heikin-Ashi, Chandelier: NO-GO.** Closed.
- **Fibonacci: already NO-GO** (prior campaign).
- **Keltner breakout: positive and real, but 82% redundant with donchian.** Not
  a new leg. The only honest way it could matter is as a *filter* on donchian
  ("take the breakout only when also ≥2×ATR extended"), which would need the full
  engine + walk-forward + DSR pipeline — and note that a comparable donchian
  filter (the BBW contraction gate) was already tried and measured NO-GO.

Multiple-testing note: this session ran a large number of cells (regime, tilt,
coin axis, 30 scalp cells, 16 slower-TF cells, eras, 10 indicators here). Keltner's
t=+4.08 is meaningful but must be DSR-deflated against that trial count before
anyone calls it validated.
