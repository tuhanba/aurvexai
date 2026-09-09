# FTMO instrument universe — exhaustive honest scan (2026-08-20)

"Use the edge in more places": test every FTMO-tradeable instrument under the
honest live-real model (no-chase + realistic gap-fill; best of ORB and PDHL) to
find any additional instrument where the breakout edge holds. Bar: expectancy
> +0.08R at a realistic 0.06% RT **and** OOS ≥ 4/5.

## Full universe result — only the two precious metals survive

| group | instruments | result |
|---|---|---|
| **precious metals** | XAUUSD, XAGUSD | ✅ **the only survivors** (ORB) |
| other metals | XPTUSD, XPDUSD, COPPER | ❌ negative even at low cost |
| energy | WTI, BRENT, NATGAS | ❌ negative / no edge |
| indices (all) | GER40, NAS100, JP225, US30, US500, UK100, FRA40, AUS200, HK50, EU50 | ❌ gap-vulnerable, ~0/negative honest |
| FX | majors + crosses | ❌ mean-reverts, dead on breakout (prior campaign) |

Honest live-real expectancy (RT 0.06%): XAGUSD +0.128, XAUUSD +0.048, everything
else ≤ +0.03 or negative, none clearing OOS 4/5. **Zero new traditional
instruments.** The ORB edge is a liquid-precious-metal phenomenon: it needs an
instrument that trends intraday and whose opening range is gap-immune. Indices
gap overnight (the no-chase skips ~half, the rest is weak); other metals/energy
don't trend cleanly intraday; FX reverts.

## Weekday-only crypto — one borderline candidate (BTC)

Crypto was previously set aside for weekend exposure. Tested **weekday-only**
(Sat/Sun skipped, session-close exit = no weekend hold), which removes that
objection entirely:

| | ORB @0.06% | OOS | ORB @0.10% |
|---|---:|:---:|---:|
| **BTC** | **+0.117** | 3/5 | +0.036 |
| ETH | +0.039 | 3/5 | −0.017 |

BTC weekday-only ORB is a **real but borderline** edge — same profile as silver:
positive, uncorrelated with the metals book (genuine diversification), but
cost-fragile (crypto CFD spreads run wide and widen in volatility; at 0.10% the
edge nearly vanishes) and OOS 3/5. ETH is too weak.

**No code change:** the EA already blocks weekend entries (Sat/Sun return), so
crypto runs weekday-only automatically. It only needs `ForceStrategy=ORB` on the
BTC chart (crypto auto-detects to PDHL, which is negative). Add as **probation**
(RiskPct 0.5, TrailStopR 0) and let KAPI-1 measure the real crypto spread —
FTMO's crypto leverage (~1:2), margin and maintenance-window specifics also need
live confirmation.

## Bottom line

The traditional-instrument universe is exhausted: **gold + silver are the only
breakout edges**, with **BTC (weekday-only ORB) a sixth borderline probation
candidate**. "Using the edge in more places" is therefore primarily **horizontal
— more funded accounts trading the same gold+silver(+BTC) book in parallel — not
more instruments.** The instrument search is closed; capital/account scaling is
the remaining breadth lever. Reproduce with the honest-fill builders on
`scripts/ftmo_trail_probe.py`.
