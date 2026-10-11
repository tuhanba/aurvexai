# Edge-discovery — first delivery: three research hypotheses (with evidence level)

Discovery method (no data fabricated): `scripts/aurvex_edge.py` reads the collector v13 DB
(clock-proven ticks only), resamples to bars, and for each bar-close as a candidate entry computes
**entry-time features** (return, volatility, squeeze = range/median-range, breakout, spread) and —
separately — **forward outcomes** (long/short after-cost return, MFE/MAE) over several horizons.
Features use only `bars[..i]`; outcomes use only `bars[i+1..i+H]` — **no future information in any
feature** (unit-tested). Output: `edge_rows.csv` + `edge_summary.md` (conditional means with
sample size n; no edge asserted from thin n).

Evidence levels: **A** reproduced out-of-sample · **B** in-sample only (weak) · **C**
hypothesis-only (not yet measured). Nothing here is above B yet — the empirical pass needs the
operator's data run (below).

| # | Hypothesis (entry-knowable → measurable outcome) | Explicit rule | Evidence |
|---|---|---|---|
| H1 | **Opening-range breakout on metals** (XAUUSD/XAGUSD): the first clean break of the opening range has positive **after-cost** expectancy in-window. Entry feature: breakout of the N-bar opening range + entry spread. Outcome: after-cost forward return to session close. | ORB first-break-wins, no TP, session-close exit (= baseline/C2 ORB). | **B→C.** In-sample 2026-09 tester net after cost +291.14 (XAU, 9 trades) / +202.27 (XAG, **1 trade**); XAG N=1 is anecdotal. Not reproduced OOS. |
| H2 | **Squeeze filter for PDHL**: prior-day/opening **low-range (squeeze) days** degrade breakout edge; requiring range ≥ trailing median removes losers. Entry feature: `squeeze = cur_range / median_range` (<1 = squeeze). Outcome: after-cost forward return, breakout vs squeeze buckets. | PDHL only when `PdhlMinRangeMedMult ≥ 1.0` (skip squeeze days). | **B.** Prior KAPI-1 research added this filter for JP225; NOT re-validated OOS in this pipeline. |
| H3 | **Metals cost gate**: when **entry spread** is large relative to the intended stop, short-horizon metal trades are net-negative **after cost**. Entry feature: `spread` at entry (and spread/stop). Outcome: after-cost return by entry-spread bucket. | Skip when `target < CostGateMult × (spread+commission+slippage)` (= C1 scalp gate). | **C.** Hypothesis-only (cost-structure argument). `aurvex_edge.py` measures after-cost return by spread bucket to test it. |

## How each is tested (same discipline as C1–C4)

1. Run discovery on the operator's data to get conditional after-cost returns + MFE/MAE with n:
   ```
   "C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe" scripts\aurvex_edge.py --db C:\Users\pc\AurvexData\aurvex_live_v13.db --bar-min 5 --lookback 20 --horizons 3,6,12 --out C:\Users\pc\AurvexData\reports_v13\edge
   ```
   Report: `edge_summary.md` (conditional means + n) and `edge_rows.csv` (per-entry features+outcomes).
   ⚠ The live collector capture is short/live; it is **not** broker tester history. Treat small n as
   anecdotal and prefer the tester matrices (C1–C4) for period coverage.
2. Convert a surviving pattern to an **explicit rule** (as in the table), realise it in a
   *candidate* EA mode (never the live EA), and run it through the `batch`→`reports` pipeline with
   spread/commission/slippage and the net-after-cost + drawdown + reached-target metrics.
3. **Record every tried hypothesis** in `research_out/hypotheses_ledger.csv` (id, feature, rule,
   horizon, evidence, status, decision). **Selected** hypotheses are validated on **reserved**
   periods not used to form them (outside V1–V3), and the ledger's examination status prevents
   reusing a tuning period as validation.

## Guardrails

- No future information in entry features (enforced + unit-tested).
- After-cost only; entry **cost gate** (modeled) is reported **separately** from **realized** cost.
- Per-symbol; **portfolio (combined-account) time-to-target is NOT measured** — a separate step.
- No edge claimed from thin n; evidence level stated for every hypothesis.
