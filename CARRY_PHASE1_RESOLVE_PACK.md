AurvexAI — Claude Code Task Pack: FUNDING CARRY · PHASE 1 RESOLUTION (close it out)

READ THIS FIRST. You are a Claude Code session running on (or with direct access
to) the engine host: you CAN reach Binance, you HAVE the data cache and Docker,
and you run tests. Your job is to END the paste-back loop and reach ONE
defensible answer: is the hedged funding carry a GO to a paper proposal, or a
NO-GO — and exactly why. Do the full general analysis, close every open thread
below yourself, and write the definitive verdict. Do not hand control back for a
single number you could have computed here.

================================================================================
0. Where we are (state you are inheriting — all merged to main)
================================================================================

The Funding Carry wave has cleared Phase 0 (gross edge) and built the Phase-1
net-on-capital hedge sim. Established, high-confidence results:

* Phase 0 (`CARRY_PHASE0_REVIEW.md`): a gross, frictionless funding edge exists,
  persists across regimes, generalises. Live universe = BTC, ETH, XRP, LINK, DOGE.
  SOL and BNB are DEAD (SOL nets ~0 with a −28.5% FTX funding bleed; BNB funding
  is structurally negative). AVAX was dropped in Phase 1 (net-negative under cost).
* Phase 1 sim (`scripts/carry_sim.py`, `scripts/carry_phase1.py`,
  `CARRY_PHASE1_REVIEW.md`): spot-long + perp-short delta-neutral, four legs of
  cost, MMR + collateral buffer, isolated vs cross margin, an intra-settlement
  basis-blowout stress, and a DRAWDOWN-based ruin gate (not a liquidation count).
* Settled findings:
  - **Isolated margin → NO-GO** (the short is liquidated on every multi-year
    rally; the spot gain sits in a separate wallet).
  - **Cross margin, settlement-level (no stress) → clean GO**: 5 majors net
    +6–8% on capital, liq=0, NW t 10–15, out-of-symbol holdout PASS. Cross margin
    is therefore REQUIRED (spot collateralises the perp).
  - Return is on DEPLOYED CAPITAL (spot notional + perp margin + buffer), ~half
    the Phase-0 gross-on-notional. This is expected and correct.

The one UNRESOLVED thread — the reason for this pack — is the **tail stress**.
Under `--stress`, XRP/LINK stayed clean but BTC/ETH/DOGE showed liquidations and
deep drawdowns. That pattern is suspect: BTC has the TIGHTEST real perp–spot
basis of the universe, so BTC dying while XRP survives points at a DATA/MODEL
artifact, not real tail risk. A just-merged fix stopped a missing spot mark from
silently reverting the cross check to isolated (it now carries marks forward and
counts `gap_settlements`), but the tail question must now be settled with data,
not more guessing.

================================================================================
1. Hard constraints (unchanged — enforce them)
================================================================================
* `LIVE_ENABLED=false` always. Research/paper only. No live path, no orders, DB
  read-only if touched.
* Paper/live parity is sacred: do not touch `DecisionEngine.decide()` or the
  existing executors. The carry sim is additive/offline.
* No secrets in code/git. Generated `*_FINDINGS.md` / `*.csv` stay gitignored.
* Test green floor: ≥ 534, nothing skipped. New logic ships with tests.
* Reuse existing utilities — do NOT reimplement: the Phase-0 data layer
  (`load_or_fetch_funding/spot/candles`, the shared paginator), `carry_sim`,
  `carry_phase1`, the `carry_phase0` significance functions, `holdout_check`.
* Branch: develop on the active carry branch, run `pytest`, commit with clear
  messages, merge to `main`. One shell command per line if you emit operator
  commands (Termius), but you should mostly run things yourself.

================================================================================
2. Mission — resolve, don't relay
================================================================================
Produce a single, defensible Phase-1 verdict backed by data you computed here.
Work the tasks below end-to-end: fix what is broken, run the full matrix,
interpret it, and write the findings + updated review. An honest NO-GO is an
acceptable outcome; a GO must survive every check below.

================================================================================
3. Tasks
================================================================================

Task A — DATA INTEGRITY AUDIT (do this first; it is the prime suspect)
The stress artifact is almost certainly a spot 8h coverage gap. Settle it:
* For each of BTC, ETH, XRP, LINK, DOGE, SOL, BNB, report side by side: funding
  settlements, perp 8h bars, spot 8h bars, each series' first/last UTC date, and
  the count of funding settlements with NO aligned spot bar (and no perp bar)
  within a tight tolerance. Use the read cache; `--refresh` the spot leg if the
  spot series is shorter than the perp series or has interior gaps.
* Confirm the perp and spot 8h candles share UTC boundaries (00/08/16). If spot
  history is shorter than funding history (e.g. spot listed later, or the fetch
  truncated), REPORT the usable overlap window and run the sim only on it.
* Deliverable: a coverage table. The hypothesis to confirm or kill: BTC/ETH/DOGE
  had spot gaps that the old code turned into fake isolated liquidations.

Task B — RE-RUN THE MATRIX with gaps visible, and interpret
Run (cross is required; isolated is the control that proves it):
* `carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE --controls SOL,BNB --margin-mode cross`
* `... --margin-mode cross --stress`
* `... --margin-mode isolated` (expected NO-GO — the "why cross" evidence)
Read the new `gaps=`/`marks_ok=` columns. Decide, with the coverage table:
* If the remaining stress liquidations sit on symbols/settlements with gaps →
  they are data artifacts; note it and rely on the gap-free result.
* If liquidations persist on gap-FREE settlements → they are REAL basis-blowout
  tail risk. Pull the actual dates and the realized perp–spot basis at those
  settlements and check them against the Phase-0 tail dates (FTX-SOL 2022-11,
  ETH-Merge 2022-09, COVID-BTC 2020-03). Real is real — respect it.

Task C — PARAMETER ROBUSTNESS SWEEP (is +6–8% a plateau or a knife-edge?)
Sweep and tabulate net-on-capital + max_drawdown + liquidations per symbol for:
* leverage ∈ {2, 3, 5}, buffer_frac ∈ {0.25, 0.5, 1.0},
  stress_basis ∈ {0.0, 0.01, 0.02, 0.05}, and a taker-fee bump (e.g. 5→8 bps).
Report where the GO holds and where it breaks. A verdict that only survives one
(leverage, buffer) point is a knife-edge NO-GO; a broad plateau is a real GO.
Add this as a `--sweep` mode or a small sibling script — reuse `simulate`.

Task D — DRAWDOWN ATTRIBUTION (what actually causes the losses?)
For each surviving symbol, decompose the max drawdown: how much comes from
sustained negative-funding regimes vs from liquidation events vs from cost drag?
Tie the worst drawdown windows to calendar dates. This is what a paper operator
must survive, so name it concretely.

Task E — OPERATIONAL DRAG (make the yield honest)
Add a conservative operational overlay and report net-on-capital after it:
collateral earns 0 (opportunity cost of the buffer), a periodic rehedge/roll
cost, and taker-only forced unwinds. If +6–8% becomes ~0 after realistic drag,
that is the finding. Keep it a documented, single conservative assumption — not a
tuned knob.

Task F — DEFINITIVE VERDICT
Update `CARRY_PHASE1_REVIEW.md` and (re)generate `CARRY_PHASE1_FINDINGS.md` with:
the coverage table, the interpreted matrix (artifact vs real tail), the
robustness sweep, drawdown attribution, operational-drag-adjusted net, and a
clear GO / NO-GO-to-paper against Section 4 — with the surviving universe and the
REQUIRED conditions (cross margin, buffer/leverage, symbol set) stated plainly.

================================================================================
4. Phase-1 → paper gate (all must hold on the honest, gap-free, drag-adjusted model)
================================================================================
* Net-on-capital positive and economically meaningful AFTER operational drag,
  broad across the surviving symbols (out-of-symbol holdout PASS), AND
* max_drawdown below the ruin threshold on a majority, with the drawdown sources
  named and survivable, AND
* the GO holds on a PLATEAU of (leverage, buffer, cost) — not a single point, AND
* block-bootstrap / Newey-West significance on NET capital returns comfortably
  positive, AND
* SOL/BNB negative controls come out non-positive, AND
* the tail-stress liquidations are either shown to be data artifacts OR shown to
  be survivable (bounded drawdown) real events — not silently ignored.
If any fails → NO-GO, stated plainly, with the reason. If all hold → GO to a
Phase-2 paper-proposal pack (both-legs cross-margined executor design). Neither
outcome is a live decision.

================================================================================
5. What NOT to do
================================================================================
No live. No paper-executor build (that is Phase 2, and gates on this verdict). No
sizing change to the existing engine. No basis-spread or perp-only strategy. No
funding forecast / regime ML. Do not relax a gate criterion to manufacture a GO —
if you change a criterion, justify it as more correct (as the liq-count → drawdown
change was) and say so.

================================================================================
6. Reproduce / run (you run these yourself; one per line)
================================================================================
cd ~/aurvexai
git pull origin main
docker compose up -d --build
docker compose exec engine python scripts/carry_data.py --universe BTC,ETH,XRP,LINK,DOGE,SOL,BNB --refresh
docker compose exec engine python scripts/carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE --controls SOL,BNB --margin-mode cross
docker compose exec engine python scripts/carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE --controls SOL,BNB --margin-mode cross --stress
docker compose exec engine python scripts/carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE --controls SOL,BNB --margin-mode isolated
(then the sweep from Task C, then write the verdict)

Finish by pasting the final GO/NO-GO line and the one-paragraph reason.
