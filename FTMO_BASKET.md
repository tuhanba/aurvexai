# FTMO trend-following basket — aggregate pass/survival

`donchian_trend` portfolio (max 6 concurrent), 3000 Monte-Carlo runs at the real trade cadence, 2-step challenge, 90-day horizon, FTMO 100k.

| basket | instruments | trades | net % | expectancy_R | cadence/day | historical path | risk | FTMO pass | survival |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| donchian 4h/1d BASKET | 11 | 520 | -4.482% | -0.0605 | 0.51 | no_target_yet (dd 21.6%) | 0.25% | 2.7% | 98.4% |
| | | | | | | | 0.5% | 18.2% | 67.3% |
| | | | | | | | 0.75% | 28.6% | 45.6% |
| donchian 1d/30d BASKET | 6 | 330 | 5.916% | 0.0498 | 0.11 | breach_max (dd 20.2%) | 0.25% | 10.7% | 99.2% |
| | | | | | | | 0.5% | 35.7% | 78.5% |
| | | | | | | | 0.75% | 43.5% | 57.1% |

## The real finding (important)

The naive "diversify into a big basket" idea **fails FTMO**, for two distinct reasons:

1. **Diversification diluted the edge at 4h.** Gold's clean 4h trend edge (+0.27R
   alone) became **−0.06R / −4.5% net** once indices + FX were pooled in — most
   of the basket does not trend as cleanly as gold, so they add noise, not edge.
2. **The daily basket is positive-expectancy but BREACHES the max-loss rule.**
   +5.9% net, +0.05R — yet the **real historical path hit −20% drawdown →
   `breach_max`.** FTMO's 10% overall limit is half that. The account would have
   blown, twice over, despite the positive expectancy.

**Why:** trend-following inherently has deep, clustered drawdowns (many small
losses between rare big wins), and a basket of **correlated** trend instruments
(metals + indices all sell off together in risk-off) draws down *together* →
portfolio DD ≫ any single instrument's. FTMO's tight 10%/5% envelope is
fundamentally hostile to that drawdown profile.

**Methodology note:** the bootstrap Monte-Carlo (35–43% "pass") is **optimistic**
— it resamples trades independently and destroys the losing-streak clustering and
cross-instrument correlation that actually cause breaches. The **historical-path
replay is the truer test, and it breached.** Trust the historical path over the
bootstrap here.

## Verdict

A raw diversified trend basket does **not** pass FTMO: 4h dilutes the edge, daily
breaches the 10% max-loss on the real path. The problem is **drawdown /
correlation**, not raw expectancy.

But this is exactly what the **FTMO governance layer already built** is designed
to fix: health-based down-sizing as drawdown grows, the compliance gate's
portfolio worst-case check, and the Survival-mode halt should keep the realised
drawdown inside the 10% envelope. **These backtests are RAW — they do not run the
governance throttle.** The decisive next test is a **governance-in-the-loop
backtest**: inject the FTMO account state + compliance gate + health sizing into
the backtester and re-run the daily gold/basket to see whether it converts the
−20% breach into a survivable, passing path.

## Next steps (revised priority)

1. **Governance-in-the-loop backtest** — thread `FtmoAccountState` + the
   compliance gate + health/mode sizing through the backtester so the raw trend
   stream is throttled by the FTMO risk engine, and measure whether drawdown
   stays < 10%. (This is the point of the whole FTMO OS — now prove it.)
2. **Cut correlation** — cap concurrent positions hard (1–2), or trade the single
   cleanest trend (gold) with strict per-trade risk, and re-measure DD.
3. Walk-forward + real FX/CFD costs before any funded attempt.

## Notes

- Portfolio = one shared FTMO account, up to 6 concurrent trend trades across the basket (the backtester's native multi-symbol mode), so the cadence is aggregate and challenge-viable.
- 'historical path' replays the realised trade stream through the daily/overall floors by CE(S)T day (realised only, no intraday floating → a lower bound on breaches). Monte-Carlo adds the distribution at the real cadence.
- Still in-sample, crypto cost model, Yahoo proxy feeds. Walk-forward + real FX/CFD costs are the next gate before any funded use.
- Reproduce: `python scripts/ftmo_basket.py`.
