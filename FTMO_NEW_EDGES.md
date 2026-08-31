# FTMO new-edge hunt + walk-forward (2026-08-03)

Goal: accelerate the funded target **without raising per-trade risk** — by adding
uncorrelated edges to the validated base portfolio (gold ORB + DAX/NAS100 PDHL).

## Method
1. `scripts/ftmo_new_edges.py` — screen a wide candidate set (other-region indices,
   energy, extra metals) under ORB and PDHL at a realistic round-trip cost.
2. `scripts/ftmo_newedge_wf.py` — take the promising ones through **5 contiguous
   out-of-sample folds** over ~2.5y of 1h data. No fitted parameters (ORB = first
   UTC hour, PDHL = prior-day range + ATR14×1.5), so this is a temporal-stability
   test — the relevant risk for adding an edge.

## Single-window screen (90d, robust at 0.10% RT)
Survivors: JP225, WTI/BRENT, HK50, EU50, XPTUSD. Rejected: US30, US500, UK100,
FRA40, AUS200, COPPER. The single window flattered the two most exciting names —
so we walk-forwarded them.

## Walk-forward isolation (base + one addition, RT 0.06%, risk 0.5%)

| fold | period | + JP225 net / maxDD | + WTI net / maxDD |
|---:|---|---:|---:|
| 1 | 24-03..24-09 | **+27.6%** / 6.0% | −7.3% / 8.5% |
| 2 | 24-09..25-02 | **+22.1%** / 7.0% | +10.8% / 6.7% |
| 3 | 25-02..25-08 | **+43.7%** / 7.1% | +24.8% / **11.3%** |
| 4 | 25-08..26-02 | **+15.5%** / 8.6% | −8.5% / 9.3% |
| 5 | 26-02..26-08 | **+72.5%** / 6.3% | +54.8% / 6.8% |
| | **positive folds** | **5/5** | **3/5** |

## Verdict

- **JP225 (Nikkei) — ADD.** 5/5 OOS folds positive, every fold's drawdown inside
  the FTMO band (≤8.6% < 10%), returns up in every fold vs base. Different region
  and a different (Asian) session, so it genuinely diversifies rather than stacking
  correlated risk. A validated fourth edge.
- **WTI (oil) — REJECT.** Only 3/5 OOS folds positive (two losing folds) and it
  breaches the 10% max-drawdown band in fold 3 (11.3%). The strong single-window
  result was a favourable recent period, not a stable edge — same discipline that
  rejected silver.

**New validated portfolio:** `XAUUSD ORB + GER40 PDHL + NAS100 PDHL + JP225 PDHL`.

## Second-pass candidates (fair per-window OOS) — all rejected

Re-tested EU50, HK50, XPTUSD, BRENT stacked on the 4-edge core, each on its own
longest common window and compared to the core on that same window. HK50/XPTUSD
add nothing. EU50 and BRENT show marginal gains but only on short, low-confidence
windows, and both fail a sanity check: EU50 is redundant with DAX (same European
correlation cluster the cap already limits), and BRENT is oil — the same asset
whose long-window sibling WTI was rejected. Verdict: **no second edge clears the
bar.** JP225 remains the single validated addition; searching further trades
overfit risk for noise.

## Third pass — FX and crypto (FTMO-tradeable)

Both run through the ORB/PDHL breakout framework, 5 OOS folds, realistic cost.

| asset | best | exp_R | folds+ | verdict |
|---|---|---:|:---:|---|
| EURUSD/GBPUSD/USDJPY/AUDUSD/USDCAD/EURJPY/GBPJPY/AUDJPY | mixed | ≤0.06 | ≤4/5 | **FX = no edge** (mean-reverts, doesn't trend-break) |
| **BTC** | PDHL | **0.207** | **5/5** | **real edge** (RT 0.10%) |
| **ETH** | PDHL | **0.331** | **5/5** | **real edge** (RT 0.10%) |

**FX is dead** on breakout — confirms its reversion nature; no FX pair is worth
adding. **Crypto (BTC, ETH) is a genuine edge** — trends hard, so prior-day
breakout works, and it is uncorrelated with the gold/index book (strong
diversification). FTMO offers both as CFDs.

**Not a drop-in, though.** Crypto trades ~24/7 on FTMO, but the current EA is
weekend-flat (an equities rule) and UTC-day-session — so it would skip crypto's
weekend moves and underperform this backtest. Integrating crypto needs: (1) a
crypto branch in the EA with weekend-aware sessions, (2) FTMO's crypto specifics
(lower leverage ~1:2, margin, maintenance window), (3) real-spread verification on
the demo (crypto spreads widen in volatility). A validated edge that requires
integration work, not a symbol you can just attach the current EA to.

## Safe-risk ceiling (acceleration sweep)

Risk sweep of the 4-edge portfolio across the same 5 OOS folds — the highest
per-trade risk at which NO fold breaches the FTMO drawdown band:

| risk % | folds + | worst-fold maxDD | verdict |
|---:|:---:|---:|---|
| **0.50** | 5/5 | **8.6%** | ✅ safe ceiling |
| 0.60 | 5/5 | 9.9% | ⚠️ at the limit (breaches with real slippage) |
| 0.70 | 5/5 | 10.7% | ❌ breach |
| 0.85–1.0 | 4/5 | 12.9% | ❌ breach |

**0.5% is already the safe ceiling** — the system is correctly sized and the risk
knob offers no free acceleration. Raising it to 0.6% adds ~5%/fold but pushes the
worst fold to 9.9%, which real fills would tip over. Acceleration therefore comes
from **added uncorrelated edges** (JP225: fold return ~23%→~36%), not more risk.

## Caveats
Yahoo proxy feeds (Nikkei via ^N225), flat cost, simplified stop-entry fills,
UTC-session anchoring. The base's per-fold and full-sample drawdowns compound over
2.5y without a challenge reset, so read the **per-fold** numbers for pass/fail. The
demo (real fills, real spreads, real session times for an Asian index) remains the
final gate before funded use. Reproduce: `scripts/ftmo_new_edges.py`,
`scripts/ftmo_newedge_wf.py`.
