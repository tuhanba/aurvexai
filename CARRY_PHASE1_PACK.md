AurvexAI — Claude Code Task Pack: FUNDING CARRY WAVE · PHASE 1 (hedge simulation, net-on-capital)

What this is. The second phase of the Funding/Basis Carry wave, unlocked by the
Phase-0 GO (`CARRY_PHASE0_REVIEW.md`). Phase 0 proved a **gross, frictionless,
on-NOTIONAL** funding edge exists, persists across regimes, and generalises
across most of the universe. Phase 1 asks the only question that decides whether
this is a real strategy or a chart: **once both hedge legs, the four legs of
fees, slippage/basis, a collateral buffer, and liquidation risk on the short leg
are modelled, what — if anything — survives as a net return ON CAPITAL?**

Phase 0's headline (+11–15% gross on notional for the live symbols) is NOT a
capital yield and must not be carried forward as one. Phase 1 replaces every
frictionless assumption with an explicit, conservative cost/collateral model and
re-asks significance on **net-of-cost capital returns**.

Hand this whole file to Claude Code. Phase 1 is a HARD GATE — paper promotion
does not begin until `CARRY_PHASE1_FINDINGS.md` is reviewed against Section 6.

================================================================================
0. Scope decisions baked in (from the Phase-0 review — do not deviate)
================================================================================

1. FUNDING HARVEST only, hedged. The position is a continuously-held
   **delta-neutral spot-long + perp-short** pair, collecting funding on the perp
   short. Basis-spread trading remains a separate, deferred hypothesis. Perp-only
   directional is still OUT (it reintroduces candle-direction dependence).
2. Hedge instrument = **SPOT** for Phase 1. Phase 0 confirmed the spot leg is
   reachable for all symbols. USDT-M/COIN-M **quarterly** hedge is an OPTIONAL
   secondary comparison (Task B note), not the primary model. Do not block Phase
   1 on quarterly.
3. Universe = the **6 live symbols**: BTC, ETH, XRP, LINK, DOGE, AVAX. SOL and
   BNB are carried ONLY as **negative controls** (SOL nets ~0 with a −28.5%
   single-episode funding bleed; BNB funding is structurally negative). The model
   must reproduce their failure — if the sim shows SOL/BNB as profitable, the sim
   is wrong.
4. This phase is about COST and CAPITAL, not signal. The entry signal is trivial
   (hold the pair); there is no threshold to tune. Do NOT introduce a funding
   forecast, a regime classifier as a hard gate, or any ML. A single
   observe-first "exit on sustained negative-funding regime" rule MAY be measured
   (Task E) but must not be tuned into the headline.
5. The realistic killer is the SHORT-LEG COLLATERAL/LIQUIDATION under a sharp
   up-move, not delta drift. Model it explicitly (Task C). Anchor stress to the
   Phase-0 tail dates.

================================================================================
1. Hard constraints (unchanged from the project, enforced)
================================================================================

* `LIVE_ENABLED=false` always. Paper/research only. No live code path touched.
* Paper/live parity is sacred. Phase 1 changes nothing in
  `DecisionEngine.decide()` or the existing executors. The carry sim is a NEW,
  additive, offline simulator; it does not route through the scalp decision path.
* No secrets in code/git.
* No risk/slot/leverage/sizing change to the existing engine. Carry sizing is a
  property of the carry sim only and is frozen at a single nominal capital for
  Phase 1 (no sizing sweep until a config clears the Section-6 bar).
* DB read-only if touched (`mode=ro`); additive-only migrations.
* Test green floor: ≥ 518 passing, nothing skipped. New sim code ships with tests.
* Reuse existing utilities — do NOT reimplement: the Phase-0 funding/spot data
  layer (`load_or_fetch_funding`, `load_or_fetch_spot`, the shared paginator);
  the conservative no-touch maker-fill rule from `src/aurvex/maker_replay.py`;
  the out-of-symbol generalisation harness pattern from `scripts/holdout_check.py`;
  the block-bootstrap / Newey-West significance from `scripts/carry_phase0.py`.
* Generated `*_FINDINGS.md` / `*.csv` are gitignored — a synthetic/local run must
  never masquerade as real evidence. Real runs happen on the engine host.

================================================================================
2. Environment conventions (Termius mobile operator)
================================================================================

* Engine container: `docker compose exec engine ...`
* Claude Code env cannot reach Binance and has no DB/cache. Author code + tests
  here; the operator runs the measurement commands on the engine host and pastes
  results back.
* Funding + spot cache already populated by Phase 0 (`data/cache/funding_*.csv`,
  spot `*_1d.csv`). Phase 1 ADDITIONALLY needs a finer-grained **perp mark/price
  and spot price series aligned to funding-settlement timestamps** to model
  entry/exit basis and the collateral path (Task A). Reuse the paginator; cache
  parallel to existing files.
* Operator commands: one per line, no `&&` chaining, numbered.
* Branch: `claude/uygula-7r2qp7` (or the active feature branch); merges to `main`.

================================================================================
3. The central question + carry-adapted acceptance bar
================================================================================

Phase 1 reports, per symbol and pooled, the **net return on deployed capital**
of the hedged carry, where deployed capital = spot leg notional + perp margin +
collateral buffer. Significance uses the SAME carry-appropriate machinery Phase 0
established (block bootstrap with block ≥ funding autocorrelation horizon;
Newey-West HAC t-stat) but now on **net-of-cost per-settlement capital returns**,
NOT gross-on-notional.

The Phase-1 → paper bar (Section 6) is deliberately stricter than the Phase-0
gate, because this is the real economics. It is NOT yet a live bar.

================================================================================
4. Tasks
================================================================================

Task A — Aligned two-leg price + collateral data (additive)
* Using the existing paginator, fetch/cache the perp mark-price (or close) and
  spot price series at a resolution that brackets each funding settlement (8h/4h
  per the Phase-0 cadence). Persist parallel to the existing cache.
* Compute realized basis `perp_mark − spot` per settlement (Phase 0 left this for
  here). This drives entry/exit cost and the collateral mark.
* Tests: alignment (every funding settlement maps to a spot+perp mark within
  cadence tolerance), cache round-trip, basis computation on a fixture.

Task B — Faithful two-leg position + cost model
* Model ONE hedged unit: open spot-long + perp-short at t0, hold, accrue funding
  each settlement, close both legs at t1. Account all FOUR legs of cost:
  enter-spot, enter-perp, exit-spot, exit-perp.
* Fees: maker where a resting limit is realistic, taker on forced unwind — reuse
  the **no-touch conservative fill rule** from `maker_replay` (a limit fills only
  if a later bar trades through it by a buffer; never on a touch). Add slippage +
  the realized entry/exit basis. Optimistic "mid fill" is forbidden.
* OPTIONAL note only: a one-paragraph comparison of how a quarterly-futures hedge
  would change leg count/cost vs spot. Do not implement it.
* Tests: four-leg cost reconciliation (Σ legs = modelled cost), maker-fill
  no-touch guard, funding accrual over a multi-settlement hold.

Task C — Collateral / liquidation model (the killer)
* Model perp-short margin with a maintenance-margin (MMR) requirement and a
  collateral buffer. On each settlement, mark the short leg; if a sharp up-move
  breaches MMR, model a **forced partial/total unwind at taker cost** (and the
  realized loss), not a free hold-through.
* Size the collateral buffer as a Phase-1 parameter (single value, frozen). Report
  the buffer level required to survive the Phase-0 tail dates without liquidation:
  FTX-SOL 2022-11, ETH-Merge 2022-09, COVID-BTC 2020-03 (and the per-symbol worst
  episodes from Phase-0 §3).
* Tests: an up-move that breaches MMR triggers a modelled liquidation; a buffer
  large enough prevents it; SOL 2022-11 path liquidates a thin-buffer harvester.

Task D — Net-on-capital harvest curve + significance
* Per symbol + pooled: cumulative NET PnL on deployed capital, net annualized
  return ON CAPITAL (state the capital definition explicitly), max drawdown, and
  the worst realized episode (including any liquidation event).
* Significance: block bootstrap + Newey-West on per-settlement NET capital
  returns (reuse Phase-0 functions; cap already raised to 200). Report CI / t-stat.
* SOL/BNB must come out non-positive (negative-control check). If they don't, stop
  and fix the model.

Task E — Static-hold vs negative-regime-exit (observe-first, not tuned)
* Phase 0 showed funding flips sign in bear/event regimes. Measure ONE simple,
  pre-committed rule: exit the pair after N consecutive negative settlements,
  re-enter after M consecutive positive ones (N, M fixed a priori, e.g. 3/3).
  Report static-hold vs this rule side by side. It is a DESCRIPTIVE comparison —
  do not grid-search N/M into the headline (that is the over-fit trap).

Task F — Out-of-symbol holdout + concentration on NET returns
* Reuse the `holdout_check` pattern: split the 6 into train/holdout symbol sets;
  the net carry must hold on the held-out symbols, and a majority of symbols must
  be individually net-positive. This is the generalisation gate (the BNB lesson).

Task G — Report `CARRY_PHASE1_FINDINGS.md`
* Per-symbol net-on-capital table; four-leg cost breakdown; collateral-buffer
  requirement + tail-date survival; net significance; static-vs-exit comparison;
  out-of-symbol holdout; and a GO / NO-GO-to-paper recommendation vs Section 6.

================================================================================
5. What Phase 1 deliberately does NOT do
================================================================================
No live. No paper promotion (that gates on Section 6). No sizing/leverage sweep.
No basis-spread strategy. No funding forecast / regime ML. No change to the
existing scalp decision path or executors. No quarterly-hedge implementation
(spot only; quarterly is a note).

================================================================================
6. Phase 1 → paper-promotion gate (stricter than Phase 0; still not live)
================================================================================
Proceed to a paper-trading proposal only if ALL hold on the NET-on-capital model:
* Net return on capital positive and economically meaningful after all four cost
  legs + collateral buffer (a token positive that any fee wobble erases is a
  NO-GO), AND
* Survives the Phase-0 tail dates without ruin at the modelled collateral buffer
  (no liquidation cascade), AND
* Broadly net-positive across the 6 (out-of-symbol holdout passes; not 1–2
  symbols), AND
* Block-bootstrap / Newey-West significance on NET capital returns comfortably
  positive, AND
* SOL/BNB negative controls correctly come out non-positive.
If any fails → funding harvest does not survive real frictions. Say so plainly;
an honest NO-GO is an acceptable outcome (as in Phase 0 and the prior wave).

================================================================================
7. Deliverable + new scripts
================================================================================
`CARRY_PHASE1_FINDINGS.md` (gitignored; engine-host generated). New scripts under
`scripts/`, consistent with the existing pattern:
* `scripts/carry_sim.py` — two-leg cost + collateral simulator (Tasks B, C).
* `scripts/carry_phase1.py` — net-on-capital curve + significance + holdout +
  static-vs-exit + report (Tasks A-pull, D, E, F, G).
New tests under `tests/` for the data + cost + collateral model. Maintain the
≥518 green floor.

================================================================================
8. Reproduce on the engine host (one command per line, no &&)
================================================================================
cd ~/aurvexai
git pull origin main
docker compose up -d --build
docker compose exec engine python scripts/carry_sim.py --universe BTC,ETH,XRP,LINK,DOGE,AVAX --refresh
docker compose exec engine python scripts/carry_phase1.py --universe BTC,ETH,XRP,LINK,DOGE,AVAX --controls SOL,BNB

Then paste `CARRY_PHASE1_FINDINGS.md` (or the console summary) back for review
against the Section 6 gate.

================================================================================
9. Open decisions deferred to AFTER Phase 1 (do not resolve now)
================================================================================
* Quarterly vs spot hedge (full cost/capital comparison, if Phase 1 passes on spot).
* Paper sizing model: capital allocation across the surviving symbols, slot caps,
  and where carry sizing lives relative to the existing risk model.
* Funding-regime exit logic promotion (only if Task E shows a robust, NOT
  over-fit, improvement).
* Engine architecture: where a both-legs paper carry executor lives so eventual
  live parity (spot + perp + funding settlement + collateral) holds.
* Live consideration: a separate, explicit go-live decision — never implied by a
  Phase-1 GO.
