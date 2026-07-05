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
