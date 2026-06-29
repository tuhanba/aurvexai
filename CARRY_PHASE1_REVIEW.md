# Carry Phase 1 — Review & Verdict (net-on-capital hedge sim)

**Status: GO to a paper proposal — CONDITIONAL on cross-margin, universe = 5.**
This is NOT a live bar, and not yet a build order for a paper executor (see §6).

This file is the human review the Phase-1 gate requires. It interprets two real
engine-host runs (isolated vs cross margin) of the two-leg cost + collateral
simulator over full realized funding + perp/spot mark history. The regenerable
findings live in the gitignored `CARRY_PHASE1_FINDINGS.md`.

Model: spot-long + perp-short delta-neutral, four legs of cost (maker 2bps,
taker 5bps, slippage 2bps, half-spread 1bp per leg), leverage 3, MMR 0.5%,
collateral buffer 0.5×notional, liq-penalty 10bps. Return is on DEPLOYED CAPITAL
(spot notional + perp margin + buffer), not notional.

---

## 1. The decisive result: collateral architecture is the gate

| Symbol | Isolated net/yr | Isolated liq | Cross net/yr | Cross liq | NW t |
| --- | --- | --- | --- | --- | --- |
| BTC  | +6.2% | 4 | **+6.0%** | **0** | 15.6 |
| ETH  | +7.3% | 5 | **+6.8%** | **0** | 14.4 |
| XRP  | +8.0% | 4 | **+7.7%** | **0** | 11.9 |
| LINK | +7.4% | 4 | **+7.4%** | **0** | 11.95 |
| DOGE | +6.8% | 5 | **+5.4%** | **0** | 10.7 |
| AVAX | −0.45% | 5 | **−4.3%** | 1 | 4.7 |
| SOL (control) | +0.5% (t=−0.11) | 6 | +2.65% (t=0.01) | 0 | — |
| BNB (control) | −0.5% (t=−0.58) | 6 | −2.4% (t=−0.19) | 0 | — |

- **Isolated margin → NO-GO.** Every symbol liquidates 4–6 times: a multi-year
  static short is force-unwound on each big rally even though the spot leg gained
  (separate wallets, no top-up).
- **Cross margin → GO.** The spot long's gain backstops the perp margin; for a
  delta-neutral pair the gains cancel the short losses, so price-move liquidation
  vanishes (0 on all 5 majors). The net funding edge survives: **+5.4% to +7.7%
  on capital, NW t 10–16.**

**Conclusion: funding harvest is viable IF AND ONLY IF run cross-margined**
(spot collateralises the perp). This resolves the Phase-0 Section-9
hedge/collateral-architecture open question with evidence, not assumption.

## 2. Surviving universe = 5 (drop AVAX)

BTC, ETH, XRP, LINK, DOGE clear every Section-6 criterion under cross margin.
**AVAX is out** — −4.3% on capital in cross (it holds through its
negative-funding regimes instead of being liquidated out), confirming the
Phase-0 review's "regime-fragile" flag. SOL/BNB remain dead negative controls.

## 3. The significance machinery earned its keep

SOL in cross shows **+2.65%/yr on capital but NW t = 0.01** — a non-trivial
annual driven by a few large funding episodes, with zero consistency. A naive
annual-sign reader would call SOL profitable; the carry-adapted significance
(block bootstrap + Newey-West) correctly rejects it as noise, and the
significance-based control gate passes it. This is the same discipline that
killed the directional-TA wave.

## 4. Honest caveats — what the GO does NOT yet prove

1. **Intra-settlement tail microstructure.** Liquidation is checked only at the
   8h settlement mark, and the model assumes perp ≈ spot. The dangerous moment
   for a cross-margined short is a squeeze where the **perp spikes above spot
   (basis blowout)** intra-period — exactly when a cascade liquidates shorts. The
   cross "liq=0" is therefore optimistic on tail microstructure; the paper phase
   must model intra-settlement marks and basis decoupling on the Phase-0 tail
   dates (FTX-SOL, ETH-Merge, COVID-BTC).
2. **Operational drag not modelled.** The +6–8% assumes frictionless continuous
   rehedging, USDT collateral earning 0, no borrow/withdrawal/transfer costs, no
   execution gaps. Real paper will shave this further.
3. **Single parameter set.** One (leverage, buffer, cost) point. A robustness
   sweep (higher taker, lower leverage, thinner buffer) belongs to the paper
   proposal before any capital assumption is trusted.
4. **Modest reward for the complexity.** ~6–8% on capital (before §4.2 drag) must
   justify a two-venue, four-leg, continuously-rehedged, cross-margined executor.
   That is a strategic call, not a data one.

## 5. Phase-1 gate verdict

Against Section 6 of `CARRY_PHASE1_PACK.md`, **cross margin passes all five
criteria** (net meaningful + broad, survives without liquidation, out-of-symbol
holdout PASS, net significance on 5 symbols, controls non-significant). Isolated
fails on liquidation. The verdict is **conditional GO: viable only cross-margined,
universe = 5**, with the §4 caveats binding on the next phase.

## 6. What this does NOT authorise

Not live. Not a paper-executor build yet. Building a both-legs cross-margined
paper executor touches engine architecture and the sacred paper/live parity, and
commits the project to the strategy operationally — that needs an explicit
decision, not an implied one. The next deliverable is a **Phase-2 paper-proposal
pack** that (a) resolves the §4 caveats (intra-settlement tail, operational drag,
param robustness) and (b) specifies where a faithful both-legs carry executor
lives so eventual live parity holds.

---

_Reviews `CARRY_PHASE1_FINDINGS.md` (gitignored, engine-host generated).
Generators: `scripts/carry_sim.py`, `scripts/carry_phase1.py`._
