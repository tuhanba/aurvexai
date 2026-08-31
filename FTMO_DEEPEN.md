# FTMO edge candidates — deepened (larger, multi-regime samples)

Follow-up to `FTMO_FX_SWEEP.md`. The first sweep's top cells had only 30–64
trades, so I grew the samples and re-measured. 2000 Monte-Carlo runs, 2-step
challenge (10% target / 5% daily / 10% max), FTMO account 100k.

## Candidate A — FX mean-reversion → **REJECTED (overfit)**

`reversion_v1 @ 1h/4h`, expanded from 6 to **13 FX pairs** (majors + crosses,
~17k hourly bars each → 118 trades):

| sample | trades | expectancy_R | winrate | risk | FTMO pass | survival |
|---|---:|---:|---:|---:|---:|---:|
| first sweep (FX, 6 pairs) | 37 | +0.191 | 41% | 0.5% | 91.6% | 100% |
| **deepened (FX, 13 pairs)** | **118** | **−0.053** | **46.6%** | 0.5% | **3.6%** | 67.8% |
| | | | | 0.75% | 13.3% | 43.1% |
| | | | | 1.0% | 21.9% | 32.2% |

The edge **vanished** on the larger sample (goes slightly negative). The +0.19R /
92%-pass first result was small-sample luck — exactly the caveat flagged in the
sweep. **Do not pursue FX intraday mean-reversion with `reversion_v1`.**

## Candidate B — gold trend-following → **HOLDS UP**

`donchian_trend` on **10 years of daily gold** (GC=F, 2512 bars — multi-regime,
far beyond the first sweep's 2-year 4h window):

| cell | trades | expectancy_R | winrate | net % (10y) | risk | FTMO pass | survival | avg DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **GOLD 1d / 30d htf** | 54 | **+0.333** | 31% | **+32.9%** | 0.5% | **86.2%** | 91.0% | 5.9% |
| | | | | | 1.0% | 71.8% | 71.8% | 7.2% |
| GOLD 1d / 7d htf | 68 | +0.188 | 29% | +19.3% | 0.5% | 70.9% | 82.0% | 7.4% |
| GOLD+SILVER 1d/7d | 143 | +0.121 | 24% | −0.3% | 0.5% | 56.1% | 62.7% | 8.3% |
| GOLD 4h/1d (first sweep) | 39 | +0.273 | — | — | 0.5% | 67.9% | 70.2% | — |

Gold trend-following is **net-positive across a decade and multiple regimes**, at
both 4h and daily, with the classic low-win-rate / high-R trend signature. Silver
drags it (don't pool them). This is a **credible signal**, not a mirage.

## Honest constraints (before anyone gets excited)

- **Frequency vs challenge speed.** Daily gold donchian makes only ~5–7
  trades/year (68 trades in 10y). The Monte-Carlo assumes trades accumulate
  faster than that, so its *time-to-pass* is optimistic. On its own, one daily
  instrument is **too slow** to pass a challenge quickly — the realistic use is a
  **basket of trending instruments** (metals + indices + trending FX) so enough
  independent trades accumulate, and/or the 4h timeframe (more trades, still
  +0.27R).
- **Still in-sample**, default (crypto-tuned) parameters, and a **crypto cost
  model**. Real gold-CFD spreads differ and must be modelled.
- **Yahoo GC=F ≠ FTMO's XAUUSD CFD** exactly (futures vs spot CFD) — close proxy.
- Moderate sample (54–68 trades). Better than the FX mirage, not yet validated.

## Verdict

**One survivor: trend-following on trending instruments (gold the clearest).**
FX mean-reversion is rejected. The path to an FTMO-viable system is a
**diversified trend-following basket**, not the crypto scalp/reversion logic.

## Next steps (priority)

1. **Build a trending-instrument basket** — gold, silver, indices (US500/NAS100/
   GER40) and trending FX/JPY crosses — run `donchian_trend` @ 4h and @ 1d as a
   portfolio so trade frequency is challenge-viable, and measure aggregate FTMO
   pass/survival.
2. **Walk-forward validate** that basket (out-of-sample splits) with a realistic
   FX/CFD cost model — the real go/no-go gate.
3. **Re-tune `squeeze_breakout`** for FX/index volatility (it fired 0 trades) so
   momentum/breakout is also testable on FTMO instruments.
4. Only after OOS holds: wire the basket as an FTMO strategy profile and
   paper-forward it behind `FTMO_MODE_ENABLED` with the compliance gate live.

*Reproduce: `python scripts/ftmo_deepen.py` (FX) and the gold-daily cells via the
same loader at `interval="1d", range_="10y"`.*
