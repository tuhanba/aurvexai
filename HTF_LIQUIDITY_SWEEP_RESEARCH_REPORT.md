# HTF_LIQUIDITY_SWEEP_RESEARCH_REPORT.md — htf_liquidity_sweep_bos_fvg verdict

**Date: 2026-07-09. Campaign 5 of the scalp/intraday edge search.**
Family requested by the owner: HTF liquidity sweep → 5m BOS / inverse-FVG
confirmation → 1m BOS execution trigger → TP at the opposite-side liquidity
draw (ICT/SMC multi-timeframe model).

**Definitive verdict: NO-GO — all 20 cells net-negative after cost; 16 of
20 negative even BEFORE cost.** The multi-timeframe confirmation stack
(5m BOS/IFVG + 1m trigger) does not rescue the liquidity-sweep family that
already failed in campaigns 1–3 as a single-TF rule (holdout −0.38R) and in
campaign 4 as prior-day sweep-reclaim (−0.32R). Zero of 12 coins positive
in the base cell; both time halves negative in every cell; every acceptance
criterion fails.

The strict spec ordering is enforced in code and was spot-verified
trade-by-trade: a level exists in the map only if it formed BEFORE the
sweep (closed-bar activation) → the sweep bar wicks the level and closes
back inside (a close through it is a break: level removed, no trade) → 5m
BOS/IFVG confirmation is searched only in bars AFTER the sweep bar (≤2h;
no confirmation → no trade; a close back through the sweep extreme cancels
the setup) → the 1m BOS trigger is searched only AFTER the confirmation
bar's close (≤1h) → entry only after the trigger. Cells run in two passes:
the original 14, then 6 spec-granularity cells (session open windows,
London/NY overlap, TP pool-type variants) — every cell counts toward the
DSR trial deflation (167 total).

## Protocol (identical to campaigns 1–4)

- Real Binance USDT-M **1m** klines from `data.binance.vision`, 24 months
  (2024-07 → 2026-06), 12 validated coins (BTC ETH SOL BNB XRP DOGE ADA
  AVAX LINK TON TRX DOT), 1,051,200 bars/coin, gapless. 5m/1h/4h frames
  resampled from the same 1m data (execution and signal frames exactly
  consistent).
- Signals on CLOSED bars only; market entries at the NEXT 1m open; limit
  entries fill only on a later touch of the resting level. No lookahead
  (spot-verified trade-by-trade).
- Conservative fills: stop-first when a 1m bar touches both stop and target.
- Costs in R against the actual stop distance: taker 0.045% + slip 0.02%
  per side (0.13% RT); resting-limit entries maker 0.02% + taker exit
  (0.085% RT). Sub-5bp stops discarded as untradeable.
- One position per symbol (no overlapping trades), setup cancelled if price
  closes back through the sweep extreme before confirmation.
- Split-half time OOS (H1 discovery / H2 confirm), kill-rule: H2 ≤ 0 kills.
- DSR via the engine's `deflated_sharpe` at the campaign-wide trial count
  **167** (147 prior book trials + 20 cells here).
- Not modeled (stated limitations): news-window avoidance (no offline
  calendar); order-book spread beyond the flat slippage charge — both would
  only make results *worse* or reduce trade count.

## Strategy implementation (as specified)

1. **HTF liquidity map** — previous UTC day H/L; previous completed Asia
   (00–08), London (08–13), NY (13–21) session H/L; last 10 unswept 1h
   pivot(k=3) swings per side; last 6 4h pivot swings per side ("major
   pools"); equal highs/lows = two 1h pivots within 0.1×ATR1h merged to one
   EQH/EQL level. Levels die when swept (wick through + close back) or
   broken (close through).
2. **Sweep** — 5m high > level & close back below ⇒ buy-side sweep, short
   bias (mirror for longs). One setup per bar/side, outermost level tags it.
3. **5m confirmation** (≤ 2h window) — BOS = close through the most recent
   confirmed 5m pivot(k=2) structure; IFVG = close through the far edge of
   the most recent opposing FVG formed into the sweep. No confirmation → no
   trade.
4. **1m trigger** (≤ 1h window) — 1m close through the prior 10-bar
   structure extreme. Entry variants: market at next open / limit at the
   broken structure (retest) / limit at the 1m displacement-FVG mid.
5. **Stops** — behind sweep wick / behind 15-bar 1m structure / behind the
   confirming IFVG far edge (each + 0.1×ATR5m buffer).
6. **TP** — nearest opposite-side liquidity level with RR ∈ [1.5, 12]
   (minimum-RR & minimum-liquidity-distance filter; no target → no trade) /
   fixed 2R / TP1 50% @1R + stop-to-BE runner to the liquidity draw /
   the draw restricted by pool type (internal 1h/4h swings vs previous
   session-and-day H/L vs equal highs/lows). Time-stop 4h.
7. **Filters** — session subsets (Asia / London / NY), open windows
   (London-open 08–10, NY-open 13–15, London/NY overlap 13–16 UTC),
   4h SMA50 trend-alignment variant.

Harness: `scripts/liquidity_sweep_wave.py` (rules pre-registered in its
docstring); data fetcher `scripts/fetch_1m_klines.py`.

## Results — all 20 cells (12 coins, 24 months)

n = trades; t/d = trades/day fleet-wide; costs included in net.

| cell | n | t/d | **net R** | gross R | cost | win | avgW | avgL | PF | t | DSR | maxDD (R) | H1 R (t) | H2 R (t) | coins+ | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 base: BOS confirm, 1m BOS mkt, sweep-wick stop, liq TP | 2,245 | 3.1 | **−0.239** | −0.045 | 0.195 | 36.7% | +1.05 | −0.99 | 0.62 | −9.6 | −9.6 | 556 | −0.204 (−5.7) | −0.274 (−7.8) | 0/12 | **NO-GO** |
| A1 confirm = IFVG | 6,261 | 8.6 | **−0.248** | −0.017 | 0.231 | 35.3% | +1.29 | −1.09 | 0.65 | −14.3 | −14.3 | 1,574 | −0.225 (−9.1) | −0.270 (−11.2) | 0/12 | **NO-GO** |
| A2 confirm = BOS+IFVG (both) | 2,085 | 2.9 | **−0.240** | −0.049 | 0.191 | 36.5% | +1.03 | −0.97 | 0.61 | −9.4 | −9.4 | 515 | −0.193 (−5.3) | −0.288 (−8.0) | 0/12 | **NO-GO** |
| B1 trigger = 5m (no 1m stage) | 2,534 | 3.5 | **−0.232** | −0.048 | 0.183 | 37.1% | +1.03 | −0.98 | 0.62 | −10.2 | −10.2 | 604 | −0.180 (−5.4) | −0.283 (−9.1) | 0/12 | **NO-GO** |
| B2 entry = limit @ structure (maker) | 2,138 | 2.9 | **−0.178** | −0.045 | 0.132 | 37.6% | +1.11 | −0.96 | 0.70 | −6.7 | −6.8 | 409 | −0.161 (−4.4) | −0.194 (−5.2) | 0/12 | **NO-GO** |
| B3 entry = 1m FVG mid (maker) | 1,588 | 2.2 | **−0.199** | −0.052 | 0.147 | 36.7% | +1.17 | −1.00 | 0.69 | −6.4 | −6.4 | 328 | −0.160 (−3.5) | −0.238 (−5.5) | 1/12 | **NO-GO** |
| D1 stop = 1m structure | 3,324 | 4.6 | **−0.409** | −0.053 | 0.355 | 27.8% | +1.94 | −1.31 | 0.57 | −13.9 | −13.9 | 1,365 | −0.295 (−6.9) | −0.522 (−12.9) | 0/12 | **NO-GO** |
| D2 stop = IFVG invalidation | 5,773 | 7.9 | **−0.486** | −0.039 | 0.448 | 24.2% | +2.49 | −1.44 | 0.55 | −19.0 | −19.0 | 2,809 | −0.431 (−11.9) | −0.542 (−15.0) | 0/12 | **NO-GO** |
| E1 tp = fixed 2R | 4,730 | 6.5 | **−0.180** | −0.022 | 0.159 | 39.6% | +0.89 | −0.88 | 0.66 | −12.1 | −12.2 | 864 | −0.161 (−7.7) | −0.199 (−9.5) | 0/12 | **NO-GO** |
| E2 tp = TP1 50%@1R + runner→liq | 2,245 | 3.1 | **−0.219** | −0.024 | 0.195 | 45.6% | +0.68 | −0.97 | 0.59 | −10.9 | −10.9 | 498 | −0.174 (−6.0) | −0.264 (−9.4) | 0/12 | **NO-GO** |
| G1 base + 4h trend alignment | 944 | 1.3 | **−0.222** | −0.013 | 0.208 | 37.0% | +1.14 | −1.02 | 0.65 | −5.5 | −5.5 | 224 | −0.201 (−3.5) | −0.243 (−4.2) | 1/12 | **NO-GO** |
| S1 base, London-only | 560 | 0.8 | **−0.201** | +0.007 | 0.208 | 37.3% | +1.19 | −1.03 | 0.69 | −3.7 | −3.8 | 125 | −0.123 (−1.6) | −0.278 (−3.7) | 2/12 | **NO-GO** |
| S2 base, NY-only | 701 | 1.0 | **−0.211** | −0.019 | 0.192 | 36.7% | +1.08 | −0.96 | 0.65 | −4.7 | −4.8 | 160 | −0.291 (−4.8) | −0.131 (−2.0) | 1/12 | **NO-GO** |
| S3 base, Asia-only | 606 | 0.8 | **−0.276** | −0.094 | 0.182 | 35.3% | +0.94 | −0.94 | 0.55 | −6.2 | −6.3 | 175 | −0.187 (−2.8) | −0.365 (−6.2) | 1/12 | **NO-GO** |
| S4 base, London-open 08–10 | 318 | 0.4 | **−0.199** | +0.023 | 0.222 | 35.8% | +1.31 | −0.94 | 0.68 | −2.7 | −2.8 | 64 | −0.193 (−1.8) | −0.205 (−1.9) | 3/12 | **NO-GO** |
| S5 base, NY-open 13–15 | 279 | 0.4 | **−0.267** | −0.037 | 0.230 | 33.0% | +1.13 | −0.96 | 0.63 | −3.3 | −3.5 | 81 | −0.375 (−3.6) | −0.159 (−1.3) | 2/12 | **NO-GO** |
| S6 base, London/NY overlap 13–16 | 353 | 0.5 | **−0.202** | +0.018 | 0.220 | 34.8% | +1.34 | −1.03 | 0.70 | −2.8 | −2.9 | 84 | −0.283 (−3.0) | −0.121 (−1.1) | 1/12 | **NO-GO** |
| T1 tp = internal liq (1h/4h swings) | 2,694 | 3.7 | **−0.219** | −0.039 | 0.180 | 37.2% | +1.00 | −0.94 | 0.64 | −9.8 | −9.8 | 613 | −0.177 (−5.5) | −0.260 (−8.4) | 0/12 | **NO-GO** |
| T2 tp = prev session/day H-L | 2,350 | 3.2 | **−0.231** | −0.039 | 0.192 | 36.9% | +1.03 | −0.97 | 0.63 | −9.5 | −9.5 | 559 | −0.192 (−5.5) | −0.271 (−7.9) | 0/12 | **NO-GO** |
| T3 tp = equal highs/lows | 1,302 | 1.8 | **−0.128** | +0.006 | 0.135 | 40.1% | +0.94 | −0.85 | 0.74 | −4.3 | −4.4 | 176 | −0.078 (−1.8) | −0.178 (−4.5) | 0/12 | **NO-GO** |

MaxDD is reported in R on the merged chronological sequence; at any live
sizing a negative-expectancy path is ruin, so the DD line only matters for
the (non-existent) positive cells.

## Required comparisons

- **BOS-only vs IFVG vs BOS+IFVG** (C0/A1/A2): statistically identical net
  (−0.24 / −0.25 / −0.24R). IFVG confirms ~3× more setups but adds no
  quality; requiring both filters trades without improving expectancy.
- **1m trigger vs 5m trigger** (C0 vs B1): identical (−0.239 vs −0.232R).
  The 1m stage neither improves entry price enough to matter nor filters
  losers.
- **Market vs limit vs FVG-mid entry** (C0/B2/B3): limit entries are the
  best variants in the family (−0.178 / −0.199R) because maker fees cut
  cost drag from 0.195R to ~0.14R — but gross is −0.05R, so nothing exists
  for the cheaper execution to save.
- **Liquidity-target TP vs fixed-R vs partials** (C0/E1/E2): fixed 2R is
  least bad (−0.180R) purely because it exits sooner; the liquidity-draw
  thesis ("price runs to the opposite pool") adds nothing measurable; the
  TP1/TP2/runner model raises winrate to 45.6% but its clipped winners
  (avgW 0.68R) lower expectancy further.
- **Stops**: wider = better here only because cost-in-R shrinks; the tight
  1m-structure and IFVG-invalidation stops are catastrophic (−0.41/−0.49R,
  cost drag 0.36–0.45R) — the exact cost-floor mechanism documented in
  `SCALP_EDGE_RESEARCH_REPORT.md`.
- **Sessions** (whole sessions S1–S3, open windows S4–S6): London and the
  London-open / London-NY-overlap windows are the only gross-positive
  slices (+0.007…+0.023R) — the sweep-reversal signal is *least bad*
  exactly where the spec expected it — but the 0.19–0.23R cost drag is
  ~10× the best gross; all end −0.20…−0.28R net. NY-open is worse than the
  NY session average. No window rescues the family.
- **TP pool type** (T1–T3): internal 1h/4h swings −0.219R ≈ session/day
  H/L −0.231R ≈ nearest-any (base) −0.239R. Equal-highs/lows targets are
  the least-bad TP in the campaign (−0.128R net, gross +0.006R, PF 0.74,
  40% win) because EQ pools sit closer (lower RR, higher hit-rate, less
  time-stop bleed) — still firmly negative in both halves.
- **Trend filter** (G1): improves gross to −0.013R while halving trades —
  directionally sensible, still dead.

## Base-cell breakdowns (n, net R, t)

- **Session**: asia 601, −0.279 (−6.2) · london 559, −0.202 (−3.7) ·
  ny 698, −0.212 (−4.7) · off-hours 387, −0.280 (−4.8).
- **Side**: long 1,112, −0.246 (−7.2) · short 1,133, −0.233 (−6.4) —
  symmetric failure.
- **Coin**: all 12 negative; best DOGE −0.083 (−0.9), worst TRX −0.566
  (−6.3). BTC −0.229, ETH −0.119, SOL −0.218, XRP −0.147, BNB −0.245,
  ADA −0.158, AVAX −0.190, LINK −0.313, TON −0.329, DOT −0.254.
- **Sweep type**: pd −0.350 (−5.2) · sess_asia −0.331 (−5.2) ·
  sess_london −0.307 (−4.5) · sess_ny −0.324 (−5.6) · sw1h −0.131 (−3.3) ·
  eq −0.052 (n=29) · **sw4h +0.196 (n=30, t=0.9)** — the only positive
  slice in the campaign: 30 trades, not significant, and a 0.04
  trades/day sub-slice of an already-failed family; under the 161-trial
  deflation this is exactly the noise the kill-rule exists for.

## Acceptance criteria (from the task spec)

| criterion | required | measured (best cell) | pass? |
|---|---|---|---|
| OOS net Exp-R | > 0 | −0.121R (best H2, S6 overlap) | **FAIL** |
| PF | > 1.1 | 0.74 (best, T3 EQ-target) | **FAIL** |
| DSR | > 0 | −2.8 (best, S4 London-open) | **FAIL** |
| Holdout pass | H2 > 0 | H2 < 0 in all 20 cells | **FAIL** |
| MaxDD acceptable | — | moot (negative expectancy) | **FAIL** |
| Cost included | yes | yes (0.13% RT taker / 0.085% maker) | met |
| No coin/session concentration | — | moot (0/12 coins positive) | — |

## Why it fails (same structural wall as campaigns 1–4)

The confirmation stack works as designed — the spot-checked trades sweep a
real level, break structure, trigger and sometimes run 3R to the opposite
pool. But across 2,245 base trades the signal has **no gross alpha**
(−0.045R before ANY cost), i.e. post-sweep direction at the 5m/1m horizon
is a coin flip with adverse selection, and the 0.13–0.45R cost drag then
buries it. This family was the last plausible variant of the
sweep-reversal thesis (single-TF versions failed in campaigns 1, 3 and 4);
the multi-TF ICT/SMC dressing changes which trades are taken, not what
they earn. **Scalp remains closed** — the reopening conditions are
unchanged: L2/tick order-flow data + latency infra, or a several-times
lower fee regime.

Campaign-wide trial count after this wave: **167**.
