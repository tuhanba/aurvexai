# Aurvex FTMO — final optimization report (2026-09-08)

The consolidated state of the system after an exhaustive optimization campaign.
This is the reference: what's in it, every validated lever, every rejected idea
(with why), and honest expectations.

## The system, in one line

A per-chart MT5 EA trading opening-range breakouts on the liquid precious metals
(gold, silver) + BTC, and prior-day-range breakouts on three indices for
variance reduction — sized low, de-risked in drawdown, each instrument tuned to
its own optimum.

## The fully-tuned configuration ($25k, EA v2.5)

| chart | strategy | RiskPct | TrailStopR | session/extra |
|---|---|---:|---:|---|
| XAUUSD | ORB | 0.35 | 0 | — |
| XAGUSD | ORB | 0.35 | 0 | — |
| BTCUSD | ORB | 0.30 | **0.3** | ForceStrategy=ORB, weekday-only |
| GER40.cash | PDHL | 0.30 | 0.5 | session 7–20 UTC |
| US100.cash | PDHL | 0.25 | 0.5 | session 14–20 UTC |
| JP225.cash | PDHL | 0.30 | 0.5 | session 0–6 UTC |

AccountSize=25000 everywhere; de-risk-in-drawdown on by default. MC pass ≈ **76%**
single-attempt (~4–5 weeks), ~94% across two attempts.

## Validated levers (all applied or ready)

1. **Per-instrument trailing** — gold/silver 0 (fat tail), indices 0.5, **BTC 0.3**
   (the pooling-miss win; keeps BTC alive at the wide crypto spread).
2. **Gold/metals timezone fix (v2.2)** — ORB reads the true 00:00–01:00 UTC hour.
3. **Index cash-session gate (v2.3)** — no more losing overnight-futures entries.
4. **De-risk in drawdown (v2.4)** — 0.6×/0.35× as the account nears the floor;
   +4pt pass rate.
5. **Low, per-instrument risk** — metals 0.35, indices 0.25–0.30; diversification
   for variance reduction; +account size enables the low % that maximises pass.
6. **BTC as a 3rd core** — +0.16R standalone, uncorrelated with metals.
7. **Ready, post-KAPI-1 (demo-verified first):**
   - **BTC multi-session** (OrbRangeHourUTC 0/3/13) — ~3× BTC trades, same risk.
   - **Volatility-conviction sizing** — size up in high vol; +~20% expectancy,
     +3.4pt pass, helps all three core instruments individually.

## Rejected ideas (tested, with evidence — do not revisit)

- Fixed take-profit, partial scale-out, trailing on metals, stall/momentum-death
  exit, peak-R exit, **Fibonacci targets** — all cap the fat tail; every one is
  net-negative or below let-it-run. The edge REQUIRES holding winners to session
  close.
- **Pyramiding into winners** — catastrophic (−0.71R); adding tightens the stop
  and intraday pullbacks whipsaw it out.
- **Cross-instrument confirmation** — the eye-catching +0.355R was a **look-ahead
  artifact** (used silver's end-of-day direction to filter gold's morning entry).
  The honest versions (time-ordered lead-lag, metals→BTC) show no usable edge.
- Entry filters — momentum, VWAP/trend alignment, breakout-bar volume (look-ahead),
  opening-range volume, regime/vol filters as hard skips — none robustly lowers
  the false-breakout rate; the vol effect is better captured by soft sizing.
- Tighter ATR stop, retest/pullback entry, entry buffer, re-entry after stop,
  dynamic instrument selection, other metals/energy/indices/FX, ETH — all
  rejected with OOS evidence.
- Trend-following (Donchian) — a real edge but its 18–91% drawdowns are
  incompatible with FTMO's −10% hard limit.

## Why we lose / why the edge is modest (structural, not fixable)

73% of breakouts fail to the −1R stop; 20% are big winners (+4R avg) that pay for
everything; the top 10% of winners make 33% of profit. This is the nature of
breakout trading. No tested filter reduces the 73% failure rate. Profit grows
only via more real-edge instruments (done), capital scaling, and discipline.

## Honest expectations

Modest edge (~+0.17–0.20R). Single-attempt pass ~76%; getting funded is likely
but not guaranteed and can take a second paid attempt. Funded income is variable
(~$1,400–1,600/mo at expectancy if the live edge holds), not a salary, and real
income realistically starts weeks after funding. Protect a runway; run this
alongside other income, not instead of it. **The live KAPI-1 data — not any
further backtest — is the arbiter of everything above.**
