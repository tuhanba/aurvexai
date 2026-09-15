# Aurvex FTMO — final optimization report (2026-09-09)

The consolidated state of the system after an exhaustive optimization campaign.
This is the reference: what's in it, every validated lever, every rejected idea
(with why), and honest expectations.

## The system, in one line

A per-chart MT5 EA trading opening-range breakouts on the liquid precious metals
(gold, silver) + BTC, and prior-day-range breakouts on three indices for
variance reduction — sized low, de-risked in drawdown, each instrument tuned to
its own optimum.

## The fully-tuned configuration ($25k, EA v2.7)

| chart | strategy | RiskPct | TrailStopR | session/extra |
|---|---|---:|---:|---|
| XAUUSD | ORB | 0.35 | 0 | `MinRangeMedMult=1.0` after KAPI-1 (gold vol-filter) |
| XAGUSD | ORB | 0.35 | 0 | — |
| BTCUSD | ORB | 0.30 | **0.3** | ForceStrategy=ORB, weekday-only |
| GER40.cash | PDHL | 0.30 | 0.5 | session 7–20 UTC |
| US100.cash | PDHL | 0.25 | 0.5 | session 14–20 UTC — **cut candidate** (see below) |
| JP225.cash | PDHL | 0.30→**0.45** | 0.5 | session 0–6 UTC; `PdhlMinRangeMedMult=1.0` after KAPI-1 |

AccountSize=25000 everywhere; de-risk-in-drawdown on by default. The v2.6 filters
ship **off** (`MinRangeMedMult`/`PdhlMinRangeMedMult=0`) — enable after KAPI-1.
MC pass ≈ **76%** single-attempt in the original book; the improved book (gold
filter, JP225 weight) Monte-Carlos higher, but note those figures are ~3pt
optimistic (they count a stuck-but-alive path as a pass; the honest "reaches +10%"
number is ~3pt lower) on top of proxy optimism. KAPI-1 is the arbiter.

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
7. **Gold low-vol-day filter (v2.6)** — skip gold days whose opening range < the
   trailing-20d median; OOS +0.19R → +0.36R, bootstrap CI lower bound > 0, and it
   **more than doubles gold's cost tolerance** (break-even 0.082% → 0.170%). Ships
   off (`MinRangeMedMult`), enable on gold after KAPI-1. `FTMO_PER_INSTRUMENT_RESEARCH.md`.
8. **JP225 is a real edge, not a diversifier** — +0.086R OOS (EA-matching, CI
   excludes 0), +0.118R with its own vol-filter (`PdhlMinRangeMedMult`). Weight it
   up (~0.45) and zero-weight NAS100/US100 (negative expectancy; break-even 0.013%,
   below any real spread). OOS-validated allocation move. `FTMO_PORTFOLIO_RESEARCH.md`.
9. **De-risk parameters confirmed optimal** — 3/0.6/6/0.35 beats both no-de-risk
   (bust 8.9%→2.5%) and a more aggressive setting (which reaches +10% *less* and
   slower). Survives block-bootstrap (streak-preserving) stress-test: +6.5pt.
10. **Execution guard + profit-lock (v2.7, default OFF)** — `MaxSpreadPct` stands
    the EA down when the live spread exceeds a per-instrument threshold (turns the
    cost break-even table into a live defence; only removes trades, never adds
    risk); `PhaseTargetPct`/`NearTargetPct`/`NearTargetMult` cut risk near the phase
    target so a near-pass isn't given back. Both tune on live/KAPI-1 (proxy has no
    spread), so they ship off.
11. **Ready, post-KAPI-1 (demo-verified first):**
   - **BTC multi-session** (OrbRangeHourUTC 0/3/13) — ~3× BTC trades, same risk.

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
- **Failed-breakout reversal (fade)** — the "most breakouts fail, so fade them"
  idea. Honest next-bar entry: loses on metals (fades away the fat-tail runners
  that carry the edge). The striking stop-at-range-edge version was a look-ahead
  artifact. Rejected.
- **Volatility-conviction / vol-targeted sizing (size UP in high vol)** — REJECTED
  (correcting an earlier "+3.4pt" note, which was an expectancy figure, not pass
  probability). At the account level, honest train/test, every variant *lowers* OOS
  pass probability: a prop challenge is variance/barrier-constrained, so levering
  into high-vol regimes adds bust risk faster than edge. The only sizing modulation
  that helps is de-risking DOWN in drawdown — never up.

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
