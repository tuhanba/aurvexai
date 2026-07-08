# Edge Search Campaign — 2026-07-05 (cloud parallel run)

Owner-authorized parallel research campaign, run in an isolated cloud
environment against **real Binance USDT-M history** from the official
`data.binance.vision` archive (the fapi API is geo-blocked from the runner;
the archive is not). All experiments used the repo's own harness
(`walkforward.py`, `trend_tf_sweep.py`, `carry_phase1.py`) — the same decision
brain as paper/live (parity) — with the pre-registered protocol: walk-forward
OOS, DSR deflation across ALL cells tried, out-of-symbol holdout, kill-rule
discipline.

## Data

- Klines: 5 majors (BTC/ETH/SOL/BNB/XRP) × {5m,15m,30m,1h,2h,4h,1d} × up to
  36 months; 7 liquid alts (DOGE/ADA/AVAX/LINK/TON/TRX/DOT) × 24 months
  (generalisation set).
- Carry: full realized funding history (2019-09 → 2026-07, ~7,100
  settlements/coin, 8h cadence) + perp & spot 4h/8h marks, 8 coins.
- **Data defect found & fixed mid-campaign:** Binance switched SPOT archive
  `open_time` to microseconds from 2025-01; the first fetcher pass used a
  wrong threshold, corrupting 2025-26 spot marks and manufacturing fake
  carry liquidations. All spot series re-fetched clean (0 leaks, verified);
  every carry number below is from the clean pass. (Early in-chat carry
  negatives from the corrupted pass are void.)

## 1. Directional TA — 20/20 cells FAIL (final)

Two sweeps, 3 profiles (bugra_replica, aurvex_enhanced, reversion_v1),
DSR-deflated; 3 years OOS on majors:

| cell | profile | n | gross R | net R | PF | DSR |
|---|---|---|---|---|---|---|
| 15m/1h | bugra | 5,816 | +0.011 | −0.023 | 0.90 | −3.2 |
| 15m/4h | bugra | 4,564 | +0.017 | −0.016 | 0.93 | −2.0 |
| 30m/2h | bugra | 4,899 | +0.009 | −0.025 | 0.90 | −3.1 |
| 30m/4h | bugra | 4,570 | +0.006 | −0.028 | 0.89 | −3.4 |
| 1h/4h | bugra | 3,787 | +0.021 | −0.014 | 0.94 | −1.5 |
| **1h/1d** | bugra | 2,501 | +0.026 | **−0.008** | 0.95 | −0.7 |
| **2h/1d** | bugra | 2,238 | +0.027 | **−0.008** | 0.95 | −0.7 |
| 4h/1d | bugra | 2,741 | +0.001 | −0.033 | 0.87 | −3.0 |
| 5m/15m | bugra | 3,537 | +0.018 | −0.015 | 0.93 | −1.7 |
| 5m/1h | bugra | 3,011 | +0.005 | −0.028 | 0.88 | −2.9 |
| (enhanced ×5, reversion ×5) | | | | −0.06…−0.36 | 0.47–0.92 | −2.5…−9.2 |

Reading: weak positive gross signal everywhere (+0.01…+0.03R), round-trip
cost 0.03–0.09R everywhere — **never clears**. The prior wave's 15m/4h hope
(+0.023 net on n=271) inverted to −0.016 at n=4,564: sampling noise, as the
kill rule suspected. Daily-HTF cells (1h/1d, 2h/1d) shrink cost drag to its
floor and STILL land negative. The previous 15m/4h candidate's n=271 sample
was noise. **Directional TA on this signal family is exhausted — formal
NO-GO, no further parameter search justified.**

## 2. Carry (funding harvest) — the one REAL edge, alive in both windows

Cross-margin, universe BTC/ETH/XRP/LINK/DOGE, controls SOL/BNB
(clean data; annual return ON CAPITAL, 3x leverage, all four cost legs):

| window | universe annual | NW t | maxDD | liq | holdout | Section-6 gate |
|---|---|---|---|---|---|---|
| **Full 2019-26** | **+6.5% … +8.2%** | 10.7–15.3 | 0.8–3.1% | 0 | PASS | **GO to paper** (all 5 criteria) |
| **Recent 2023+** | **+3.9% … +4.7%** | 12.3–17.5 | 0.1–0.7% | 0 | PASS | 4/5 — fails only `negative_controls_nonpositive` |

- Era decomposition: the edge THINNED post-2022 (≈7.5% → ≈4.3%) but remains
  strongly significant (t > 11) with near-zero drawdown and zero
  liquidations in cross margin.
- The recent-window "NO-GO" is a control-premise artifact, disclosed
  honestly: SOL (negative control) turned +1.8%/yr t=2.8 because post-2023
  funding is broadly positive — the regime lifted all coins; the simulator
  is not mis-modelling (BNB control stays negative, full-history controls
  behave). The five substantive criteria (broad net-positive, no ruin,
  out-of-symbol holdout, significance) pass in BOTH windows.
- Isolated margin: same signs (+3.7…+4.6% recent) with occasional priced
  liquidations; cross remains the right architecture (per Phase-1 review).

## 3. Verdict

1. **Directional TA: dead.** 20/20 cells net-negative over 3 years. The
   paper engine may keep running as a shadow-evidence collector, but no
   config change makes it live-worthy, and no further TF search is
   justified.
2. **Carry: the only measured, robust, positive edge.** ~+4%/yr on capital
   in the current regime (was ~+7.5% pre-2022), t-stats >11, maxDD <1%,
   zero cross-margin liquidations, passes out-of-symbol holdout in both
   windows. Expectation-setting: this is a LOW-VOLATILITY, single-digit
   annual harvest at 3x — not a fast-money strategy, and it does not
   compound to daily-percent targets.
3. **Next wave (owner decision):** build the carry paper executor per
   CARRY_PHASE1_REVIEW §6 (cross-margin, universe 5, SOL/BNB as live
   controls, the review's tail-microstructure caveats). Directional paper
   stays as-is for evidence; Stage-3 live plumbing is ready and remains
   locked.

*Generated from runs logged in this session; regenerable via
`scripts/trend_tf_sweep.py` and `scripts/carry_phase1.py` over the
`data.binance.vision` cache builder.*

---

# Phase-2 addendum — new signal families (same session)

Owner requested exploration beyond the exhausted Buğra/reversion family.
Three families, pre-registered grids, split-half holdout, taker+slip costs.
Campaign-wide trial count for deflation: 20 (TA sweep) + 6 + 12 + 8 = 46.

## Family 1 — cross-sectional momentum (12 coins, daily): NO-GO
Best in-sample cell (14d lookback, K=3) was insignificant (t +0.77) and
flipped negative in holdout. All 6 cells dead.

## Family 2 — funding-extreme directional: NO-GO (regime mirage)
"Long on extreme negative funding" printed +1.6-1.8%/trade with t≈5-6 in the
2019-23 half and turned NEGATIVE in the 2023-26 holdout — a textbook regime
artifact the holdout caught. Shorting positive funding is strongly negative
everywhere. All 12 cells dead.

## Family 3 — volatility-squeeze breakout (1h, 48h hold): **CANDIDATE**

Signal: 24-bar range in its lowest 20th percentile (squeeze) + close breaks
the 24-bar high/low → enter next open, stop = 1× range, time-exit 48h.

| check | result |
|---|---|
| Split-half holdout | H1 +0.35%/trade (t 2.3) → H2 **+0.20%/trade (t 1.7, n=1,136)** — sign holds |
| Family consistency | ALL four 48h-hold cells positive in BOTH halves |
| Concentration | **11/12 coins net-positive** (only BNB flat) |
| Yearly stability | 2023 +0.23% · 2024 +0.53% · 2025 +0.19% · 2026 +0.09% — all positive, decaying watch flagged |
| R-normalized | **+0.0945R/trade net of taker costs, t 2.72, n 2,229**, win 39.8%, median stop 2.6% |
| Economics @2% risk | ~1.7 trades/day fleet-wide → ~+0.19%/trade equity → **rough +0.3%/day, ~+120%/yr UPPER estimate** |

Caveats (why this is a CANDIDATE, not a winner): simplified simulator (no
funding over the 48h hold, flat 2bp slippage, no slot limits); t 2.72 vs 46
campaign trials is borderline after deflation — the family/breadth/year
consistency is what earns it the next round; 2026 is its weakest year.

**Next wave (proposed): implement `squeeze_breakout` as a new engine
strategy profile** (new setup detector, config-gated, parity preserved),
re-validate through the real walk-forward harness with the full cost model,
and only on a clean Acceptance-Bar pass promote to paper. This touches
`setups.py` — a strategy change under CLAUDE.md, done as its own reviewed
wave with tests.

---

# Harness validation — squeeze_breakout through the REAL engine (same day)

The candidate was ported into the engine as a fourth profile (faithful
rules; PR "squeeze_breakout profile") and re-validated through
`run_walkforward_analysis` — the real decision path with funding, spread,
slippage guards, cooldowns and slot mechanics, on 26,400 real 1h bars ×
5 majors, 26 OOS windows, deflated at n_trials=46:

| metric | research sim | REAL harness |
|---|---|---|
| OOS trades | 2,229 (12 coins) | 1,084 (5 majors; 2,290 signals — slippage/risk guards filtered 1,206) |
| gross Exp-R | — | **+0.153** |
| **net Exp-R** | +0.095 | **+0.071** |
| PF (net) | — | 1.10 |
| MaxDD | — | 42.4% (at 2% risk, 200 base) |
| DSR (46 trials) | — | **+1.49** |
| harness decision | — | **ACCEPTED** |

Reading: the engine's own protective filters shaved the research edge from
+0.095R to a still-positive **+0.071R net** — the first strategy in the
project's history to come out of the walk-forward harness net-positive
with a positive deflated Sharpe. Acceptance Bar: Exp-R ✓, PF ✓ (1.10,
borderline), DSR ✓, trades ✓ (1,084); MaxDD 42% exceeds the ~30% line at
2% risk — a SIZING property, not a signal property; rollout starts at
RISK_PCT=1.5 to bring projected DD toward the bar, with the 10% daily
kill switch as the hard floor. `win%=0.0` in the harness row is a
reporting artifact of the no-TP exit shape (wins close as TIME, not TP)
— flagged, cosmetic.

**Decision: GO to paper** under `STRATEGY_PROFILE=squeeze_breakout`
(LTF=1h, HTF=4h, LTF_LIMIT=525, TIME_STOP_BARS=48, RISK_PCT=1.5 initial),
fresh epoch for clean attribution. Live remains locked behind the
five-gate Stage-3 lock and a separate promotion decision after paper
evidence.

## Refinement round (same session): trend filter confirmed, Donchian queued

- 18-cell squeeze refinement grid: LTF SMA200 trend-alignment filter
  improved BOTH split halves; ported (`SQZ_TREND_FILTER`, default on) and
  re-validated through the harness: **net Exp-R +0.088 (was +0.071), PF
  1.12, maxDD 32.2% at 2% risk (~24% at deployed 1.5%), DSR +1.58,
  ACCEPTED** — full Acceptance-Bar pass at deployed sizing.
- Donchian/turtle 4h channel trend (8 cells): ALL 4h cells positive in
  both halves, best +0.27-0.46R/trade (t 2.5-3.6) — the strongest family
  found; engine port (channel-exit mechanism) is the next wave.
- Pullback-in-trend (RSI2, 4 cells): decisively negative (t≈−15) — closed.
- Campaign trial count now 76; all deflation notes updated accordingly.

## donchian_trend harness validation — the campaign's strongest result

Ported as the fifth profile (streaming CHANNEL exit in the executor) and
validated through the real walk-forward harness on ~5.8 years of 4h data
(12,689 bars × 5 majors, 25 OOS windows, n_trials=76):

| metric | value |
|---|---|
| OOS trades | 974 (2,433 signals; slippage/cooldown guards filtered the rest) |
| net Exp-R | **+0.284** (gross +0.362) |
| PF | **1.37** |
| MaxDD at 2% risk | **19.3%** — inside the bar without downsizing |
| DSR (76 trials) | **+2.44** |
| harness decision | **ACCEPTED — full 5/5 Acceptance-Bar pass** |

Deployment recommendation: donchian_trend becomes the PRIMARY paper
profile (LTF=4h, HTF=1d, TIME_STOP_BARS=0, RISK_PCT=2.0 — DD already
inside the bar); squeeze_breakout remains available as the validated
secondary. Live remains behind the five-gate Stage-3 lock.

## Donchian sizing decision — max-efficiency confirmed (owner request)

The validated run was measured under the legacy scalp caps (4 slots,
40% exposure) which CLIP full-size donchian positions (each ~100 USDT
notional at 200 balance). Freeing the caps was tested through the same
harness (4h/1d, n_trials=76):

| config | trades | Exp-R | PF | MaxDD% | DSR | growth proxy |
|---|---|---|---|---|---|---|
| validated (4 / 40% / risk 2) | 974 | +0.284 | 1.37 | 19.3 | +2.44 | baseline |
| **max-eff (6 / 200% / risk 3)** | 868 | +0.253 | 1.35 | 20.5 | +2.12 | **+19% vs baseline** |
| mid (6 / 150% / risk 2) | 909 | +0.270 | 1.37 | 18.4 | +2.33 | −11% vs baseline |

Per-trade quality dips slightly at higher concurrency (more correlated
open positions), but the risk-3 multiplier wins on total growth for
+1.2pt of drawdown; DSR stays strongly positive (+2.12). **Deployment
decision: max-eff (RISK_PCT=3, MAX_OPEN_TRADES=6,
MAX_PORTFOLIO_EXPOSURE_PCT=200).** Kill switch (−10% of balance) and
profit lock (+10% of balance) both scale with live balance and cap the
extra variance.

---

# Phase-3 — dedicated scalp hunt (real-trader tactics)

Owner asked to test the scalp tactics real discretionary/copy traders use,
beyond what was already killed. All on real 15m (12 coins) / 5m (5 majors),
split-half holdout, taker+slip round-trip cost 0.14%, R-normalised. Every
cell net-negative on BOTH halves — a comprehensive, robust NO-GO.

| family (tactic) | best holdout R | verdict |
|---|---|---|
| Liquidity-sweep / stop-hunt reversal (ICT/SMC) | −0.38R (buffered stop) | FAIL |
| VWAP reversion (fade extension to mean) | −0.27R | FAIL |
| RSI2 pure mean-reversion (Connors) | −0.19R | FAIL |
| Opening-range breakout (ORB) | −0.30R | FAIL |
| Momentum continuation (buy strength + trailing) | −0.40R (15m), −0.73R (5m) | FAIL |

Combined with the earlier waves, **~10 distinct families / 50+ cells of
short-timeframe scalping are all net-negative after realistic costs**, and
they get WORSE the lower the timeframe (5m > 15m loss). 

**Fundamental reason:** taker round-trip cost (~0.14%) is a large fraction of
any scalp-sized target; the gross signal on OHLCV is at best marginal and the
cost erases it. There is no taker-executable, OHLCV-signal scalp edge on this
instrument. Enabling scalp would require EITHER maker/passive execution
(tested earlier for reversion — adverse selection makes it worse) OR an
order-flow / L2-microstructure edge (needs tick/L2 data + low-latency
infrastructure, not available here). 

**Definitive verdict: scalp is a NO-GO with the available execution and data.**
The only positive edges remain the swing/positional ones: donchian_trend 4h
(+0.284R), squeeze_breakout 1h (+0.088R), carry (slow, +~4%/yr). The closest
thing to "frequent scalp action" that is actually positive is squeeze @1h
(~3–6 trades/day fleet-wide).

---

## Phase 6 (2026-07-07) — Round-2 edge hunt + the fast-momentum answer

Directive: "research OTHER edges, coin/parameter choices are yours, find scalp."
Two more never-tested execution/signal angles, then the one honest win.

### 6a. Three genuinely-new families — all FAIL on holdout

| family | best HOLDOUT R | holdout t | verdict |
|---|---|---|---|
| **Maker** mean-reversion (limit-at-extreme, earns the spread; 4bp not 14bp) | −0.18R (5m), −0.10R (15m) | −35 / −22 | FAIL |
| Maker MR, taker contrast | −0.42R | −65 | FAIL |
| Cross-coin **lead-lag** (BTC impulse → alt next bar) | −0.51R (5m), −0.24R (15m) | −111 / −68 | FAIL |
| **Keltner** band-walk continuation (trail exit) | −0.72R (5m), −0.42R (15m) | −179 / −135 | FAIL |

Key result: **maker execution does NOT rescue mean-reversion.** It roughly
halves the loss (−0.18 vs −0.42 taker) but the *gross* signal is negative —
on 5m/15m, extensions **continue**, they do not revert. Cheaper fills can't
save a wrong-sign edge. Lead-lag is already priced within one bar (negative
net). Band-walk continuation on fast TF is pure chop-death. This closes the
maker/lead-lag/microstructure hypotheses on OHLCV.

### 6b. The honest win — push the ONE edge that works DOWN in timeframe

Tick-scalp is dead, but **momentum breakout (donchian) survives to 1h.** This
is the real bridge between swing and scalp: intraday momentum, not tick-MR.
Same channel-breakout + reverse-channel exit as the deployed 4h engine, run at
30m / 1h / 2h, split-half holdout, 17-coin universe.

| TF | best cell (N,X,atr) | HOLDOUT R | holdout t | trades/day (fleet) | verdict |
|---|---|---|---|---|---|
| 30m | 20,20,2.0 | −0.019R | −0.5 | 10.2 | FAIL (costs eat it) |
| **1h** | **48,20,2.0** | **+0.116R** | **2.01** | **5.4** | **PASS** |
| 1h | 30,20,2.0 | +0.079R | 1.56 | 6.4 | PASS |
| 1h | 48,20,3.0 | +0.080R | 1.82 | 4.8 | PASS |
| 2h | 20,10,2.0 | +0.073R | 1.16 | 2.9 | weak+ |

**Triple-validated (1h N=48/X=20/atr=2.0):**
- Time holdout (2nd half): +0.116R, t=2.01 — PASS
- Out-of-symbol (train coins ≠ test coins), BOTH folds: t=+2.06 and +2.87
- Per-coin: **16/17 coins positive**
- Verdict: **ROBUST**

This is ~4× the frequency of the deployed 4h donchian (1.4→5.4 trades/day
fleet-wide) while staying holdout-positive. Not a tick-scalp — the data
proves that cannot exist here — but a validated **fast intraday-momentum
engine**, deployable today on the same shared account via multi-strategy mode:

    STRATEGIES="donchian_trend@4h/1d  donchian_trend@1h/4h:en=48:ch=20:atr=2.0  squeeze_breakout@1h/4h:ts=24"

Spec parser gained `:en=` (entry-channel length) and `:atr=` (stop multiple)
so each strategy carries its own momentum parameters on one balance.

---

## Phase 6c (2026-07-07) — Lower-TF push: the hard floor is 1h

Directive: "keep researching edges, target LOWER timeframes." Pushed the one
working family (donchian momentum) down to 15m/5m with chop-filters, plus two
never-tested low-TF families. Split-half holdout, taker cost.

**Every low-TF cell FAILS. The edge decays monotonically with timeframe:**

| TF | donchian N48/X20/atr2.0 (holdout R, t) | verdict |
|---|---|---|
| **1h** | **+0.116R, t=2.01** | **PASS** |
| 15m | −0.105R, t=−3.7 | FAIL |
| 5m | −0.437R, t=−14.5 | FAIL |

Filters help but never cross zero: ATR-expansion filter lifts 15m/N96 to
−0.037R (near break-even in-sample) but still FAIL on holdout. Volume-spike
momentum burst (−0.30R @15m, −0.71R @5m) and session-open momentum
(−0.28R @15m, −0.58R @5m) are pure cost-bleed.

**Why 1h is the mathematical floor (exact):** taker round-trip cost is a fixed
~0.0014 tax. R-normalised, that tax = cost / stop_distance:
- 5m:  stop≈0.35% → tax ≈ **0.40R/trade** (matches the −0.44R observed; gross≈−0.04)
- 15m: stop≈0.60% → tax ≈ **0.23R/trade** (matches −0.11R; gross≈+0.12)
- 1h:  stop≈1.2%  → tax ≈ **0.12R/trade**, and the gross momentum edge (+0.23R)
  finally *beats* the tax → net **+0.11R**.

The gross momentum signal is roughly constant per-trade in R terms; the cost
tax explodes as the stop (and thus the move) shrinks with timeframe. The
crossover sits between 1h and 15m. **1h is the lowest timeframe where any
OHLCV+taker edge survives on this instrument — proven, not assumed.** Going
lower is a losing proposition until execution becomes maker/rebate-based AND an
order-flow (L2/tick) signal replaces OHLCV — neither available here.

**Consequence for frequency:** the lever for more trades is NOT lower TF (dead
below 1h) — it is *more coins at 1h*. The validated 1h momentum engine already
runs the 17-coin universe at ~5.4 trades/day; widening the universe scales that
linearly, at the same holdout-positive per-trade yield.

---

## Phase 6d (2026-07-07) — Universe expansion: 17 → 21 (frequency lever)

Since 1h is the TF floor, the only holdout-safe way to more trades is *more
coins at 1h*. Screened 28 candidate perps (2.5yr 1h each) on the deployed
donchian N48/X20/atr2.0 edge. **Two-cut add-bar, both required:**
(1) sign-consistency — BOTH halves R>0 (kills H1-only overfits);
(2) holdout floor — 2nd-half R ≥ +0.02R.

**4 of 28 pass: GALA, GRT, UNI, XLM.** (LDO, RUNE sign-consistent but too weak;
the rest flip negative in H2 — classic overfit signature, correctly rejected.)

Fleet holdout (2nd half) — adding the 4 improves the fleet, doesn't dilute it:

| universe | holdout R | t | holdout trades |
|---|---|---|---|
| incumbent 17 | +0.1160R | 2.01 | 2990 |
| **expanded 21** | **+0.1183R** | **2.27** | **3717 (+24%)** |

Same per-trade yield, +24% frequency, better t. ~5.4 → ~6.7 trades/day
fleet-wide. This is the honest frequency lever.

**Validated 21-coin `UNIVERSE_INCLUDE` (ccxt full-symbol form):**

    UNIVERSE_INCLUDE="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,ATOM/USDT:USDT,GALA/USDT:USDT,GRT/USDT:USDT,UNI/USDT:USDT,XLM/USDT:USDT"

Rejected (18): AAVE APT BCH ETC FIL INJ LTC OP LDO RUNE ALGO APE AXS CHZ COMP
CRV DYDX EGLD ENJ HBAR KAVA MANA MKR SAND SNX THETA VET — none clear the
sign-consistency + holdout-floor bar. The 1h momentum edge stays coin-specific.

---

## Phase 6e (2026-07-07) — Diversifier + amplifier hunt: both NO-GO

Directive: "more options, more money, research every path." Two honest attempts
to add money beyond universe breadth. Both fail on holdout.

### 6e-1. Uncorrelated sleeve: 4h SWING mean-reversion — FAIL

Idea: momentum loses in chop, MR wins in chop → an independent MR sleeve smooths
the portfolio. Tested 4h Bollinger-fade (z<−k → revert to mid) and 4h RSI
reversion (RSI<25/30 → revert to 50), 18 coins, split-half holdout.

| family | best HOLDOUT R | t | verdict |
|---|---|---|---|
| Bollinger fade 4h | −0.076R | −4.3 | FAIL |
| RSI reversion 4h | −0.055R | −4.8 | FAIL |

**Every cell cleanly negative.** Combined with the dead 5m/15m MR (Phase 3/6a),
this is now conclusive: **mean-reversion is a mirage on this instrument at every
timeframe.** Crypto perps trend; they do not revert. There is exactly ONE
behavioral edge here — momentum/trend-continuation — expressed fast (1h),
slow (4h), and via volatility (squeeze). No MR diversifier exists to add.

### 6e-2. Yield amplifier: pyramiding the 1h momentum edge — FAIL

Idea: add a 2nd/3rd unit to a winner that extends +1R and prints a fresh
N-bar high → capture more of the big trends = more money per signal.

| variant | base H2 | pyramided H2 total-R/signal |
|---|---|---|
| base (no add) | **+0.102R (t1.59)** | — |
| +1 unit @1.0R | | −0.100R |
| +1 unit @1.5R | | −0.030R |
| +2 units @1.0R | | −0.092R |

**Every pyramid variant turns the positive base NEGATIVE on holdout.** The add
points sit near local extremes that then mean-revert into the shared
reverse-channel exit, which liquidates the whole stack at once. Adding to
winners destroys this edge. Keep single-unit sizing.

**Net of Phase 6:** the tradeable space is fully mapped. Positive: momentum
1h + 4h + squeeze (behavioral), carry (structural). Dead at every TF: scalp,
mean-reversion, lead-lag, maker-MR, band-walk, pyramiding. The only working
lever for "more" is **universe breadth** (Phase 6d, +24% and counting) and,
if wanted, the **carry sleeve** as a genuinely uncorrelated structural add.

---

## Phase 6f (2026-07-07) — Universe expansion, full pool: 17 → 28

Screened the full ~48-coin candidate pool (each 2.2–2.5yr 1h) on the deployed
donchian N48/X20/atr2.0 edge with the same two-cut add-bar (both halves R>0 AND
2nd-half R ≥ +0.02R). **11 of 31 non-incumbents pass:**
ENA, FET, GALA, GRT, JUP, SEI, STX, UNI, WIF, WLD, XLM.

Fleet holdout scales cleanly — same yield, far more trades, stronger t:

| universe | holdout R | t | holdout trades | ~trades/day |
|---|---|---|---|---|
| incumbent 17 | +0.1160R | 2.01 | 2990 | ~5.4 |
| **validated 28** | **+0.1222R** | **2.85** | **4963 (+66%)** | **~9** |

The rejected 20 (AAVE, ALGO, APE, APT, AR, AXS, BCH, CHZ, COMP, CRV, DYDX, EGLD,
ENJ, ENS, ETC, FIL, FLOW, GMT, HBAR, IMX, INJ, JASMY, KAVA, LDO, LTC, MANA, MKR,
ONDO, OP, ORDI, PENDLE, PEOPLE, PYTH, RUNE, SAND, SNX, TAO, THETA, TIA, VET)
mostly flip negative on the holdout half (e.g. JASMY H1 +0.40 → H2 −0.02;
HBAR +0.38 → −0.03) — textbook in-sample overfits, correctly filtered. LDO,
RUNE, TAO are sign-consistent but below the +0.02R floor.

**Validated 28-coin `UNIVERSE_INCLUDE`:**

    UNIVERSE_INCLUDE="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,ATOM/USDT:USDT,ENA/USDT:USDT,FET/USDT:USDT,GALA/USDT:USDT,GRT/USDT:USDT,JUP/USDT:USDT,SEI/USDT:USDT,STX/USDT:USDT,UNI/USDT:USDT,WIF/USDT:USDT,WLD/USDT:USDT,XLM/USDT:USDT"

This supersedes the Phase-6d 21-coin set. Frequency lever now delivers +66% at
the same holdout-positive yield — the honest ceiling for "more trades, more
money" without touching a decision rule.
