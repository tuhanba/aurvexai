# Outside-eye research — reduce loss / raise profit (2026-09-08)

Stepping back and asking, from a fresh quant's eye: what would genuinely reduce
the loss or raise the profit that hasn't been tried? Two first-principles ideas,
one rejected, one validated.

## ❌ Pyramiding into winners — REJECTED

Idea: profit is entirely in the 20% big winners, so ADD to a position as it runs
(amplify the fat tail without touching the 73% losers). The peak-R analysis
(reaching +XR predicts continuation) seemed to support it.

Result: **catastrophic.** Adding a unit at +1R and moving stops to breakeven took
the core from +0.172R to **−0.707R** (total −1127R, OOS 0/5). Every pyramid
variant deeply negative. Why: adding tightens the effective stop, and the large
intraday pullbacks (which the wide original stop rides through) whipsaw the added
unit out before the recovery. This edge is **fragile to any stop-tightening** —
the same reason trailing, stall and peak-R exits all lose. Confirmed again: the
wide original stop + session-close exit is essential; do not pyramid.

## ✅ Conviction sizing by volatility — VALIDATED

Idea: instead of FILTERING (which loses on frequency), keep every trade but SIZE
it by conviction — bigger in high volatility, smaller in low. Motivated by the
regime analysis (high-vol is the edge's best regime, +0.20 to +0.65R; the only
negative cell is TREND+low-vol).

Result: sizing risk by the instrument's 20-day realised-vol percentile
(weight ≈ 0.5 + percentile, average 1.0, so same total risk) lifts the
risk-weighted expectancy from **+0.172R to +0.20–0.22R (~+20%)**, OOS 5/5, with
NO loss of trade frequency. Crucially, the Monte-Carlo confirms it raises the
**pass probability, not just expectancy**: core pass rate **73.5% → 76.9%**
(+3.4 points) — the added variance does not offset the gain.

This is a genuine, robust, economically-sound lever: high-vol days have larger
intraday ranges and stronger breakout follow-through, so tilting risk toward them
captures more of the edge.

### Caveats before implementing
- The exact weight mapping (0.5 + percentile) has fitting freedom; the robust,
  economically-motivated part is the DIRECTION (more vol → more size), which is
  consistent across schemes and OOS-stable. Use a simple clamped mapping live.
- It needs new EA code (per-instrument realised-vol + a second risk multiplier
  stacking with the de-risk one) that must be **demo-verified** — do not add
  untested complexity to the live launch. Sequence it as a post-KAPI-1 upgrade
  alongside BTC multi-session, once the core is proven live.

## Net
The core exit/entry structure is confirmed optimal yet again (pyramiding, like
every early-exit/stop-tighten idea, fails). The one new profit lever is
**volatility-conviction sizing** (+~20% expectancy, +3.4pt pass), validated and
documented, to implement after the live foundation holds.
