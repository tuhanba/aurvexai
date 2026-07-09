# AurvexAI — Complete Research Dossier

*Self-contained summary of all quantitative research and engineering to date,
written to be handed to another Claude/analyst as full context. Everything
below was measured on REAL Binance USDT-M history (the official
`data.binance.vision` archive), using the engine's own walk-forward harness
(same decision brain as paper/live — parity), with a pre-registered protocol:
walk-forward out-of-sample (OOS), Deflated-Sharpe (DSR) penalty across every
cell tried, out-of-symbol holdout, and a kill-rule (drop a hypothesis the
moment holdout inverts). "R" = risk-normalised return per trade (1R = the
per-trade stop budget). Costs charged: taker 5bp + slippage 2bp per side
(round-trip ≈ 0.13%), plus funding where relevant.*

---

## 1. What the system is

AurvexAI is a clean-core crypto-futures engine on Binance USDT-M perps. One
decision brain shared across paper / live / backtest (parity is sacred).
Explicit risk model: % risk per trade, daily loss kill switch, daily profit
lock, exposure cap, per-symbol cooldown, one position per symbol. Paper by
default; a five-gate lock guards any real order (all default OFF).

## 2. Methodology (why the results are trustworthy)

- **Walk-forward OOS**: parameters fixed, tested on unseen forward windows.
- **DSR deflation**: the more cells you try, the higher the significance bar —
  guards against "try 100 things, crown the lucky one."
- **Out-of-symbol holdout**: an edge must hold on coins NOT used to pick it.
- **Split-half**: pick on the first half of history, confirm on the second.
- **Kill-rule**: if the holdout/second-half inverts sign, the hypothesis is
  dead — no re-tuning to rescue it.
- **Honesty checks**: a data defect (Binance spot archive switched to
  microsecond timestamps in 2025, corrupting marks) was caught mid-campaign
  and every affected number re-run clean.

## 3. What was TESTED and KILLED (the graveyard)

| Family | Timeframes | Verdict | Why |
|---|---|---|---|
| Directional TA (Buğra 5-cond, ATR-stop, fixed-%) | 5m→4h entry × 15m→1d trend, 20 cells | **NO-GO** | Weak positive GROSS signal everywhere (+0.01…+0.03R), round-trip cost (0.03–0.09R) never cleared. Net-negative in all 20 cells over 3 years. |
| Cross-sectional momentum (long top-K / short bottom-K) | daily, 12 coins, 6 cells | **NO-GO** | Best in-sample cell insignificant (t 0.77), flipped negative in holdout. |
| Funding-extreme directional (long crowded-short funding) | 8h settlements, 12 cells | **NO-GO** | +1.6–1.8%/trade with t≈5–6 in 2019–23, turned NEGATIVE in 2023–26 holdout. Textbook regime mirage the holdout caught. |
| Pullback-in-trend (RSI2 dip in SMA200 trend) | 1h, 4 cells | **NO-GO** | Strongly negative (t≈−15) both halves. |
| Mean-reversion v1 (Bollinger stretch) | 1m/5m | **NO-GO** | Cost-killed; gross edge eaten by round-trip cost. |

**The recurring lesson: on this instrument, fast directional scalping has no
net edge.** The signal exists in the gross tape but round-trip cost erases it,
and it dies faster the lower the timeframe (5m Donchian: −0.44R; every scalp
cell measured net-negative). This is not an implementation flaw — it is the
market's cost/edge structure.

## 4. What WORKS (validated, positive edges)

### 4a. donchian_trend @ 4h — the strongest edge
20-bar channel breakout, 2×ATR stop, exit on 20-bar opposite-channel break
(no profit target — winners run). Later refined with an LTF SMA200
trend-alignment filter (improved both split halves).

| metric (real 4h, ~5.8 yr, 25 OOS windows, DSR-deflated n_trials=76) | value |
|---|---|
| OOS trades | 974 |
| net Exp-R | **+0.284** (gross +0.362) |
| PF | 1.37 |
| MaxDD @2% risk | 19.3% |
| DSR | **+2.44** |
| harness | **ACCEPTED (5/5 Acceptance-Bar)** |

Character: swing, not scalp. Positions hold days; ~35–45% win rate; a few big
trend-runners carry the P&L. Cannot be sped up — the edge dies below 4h
(1h/2h weak, t<1; 30m and below negative).

### 4b. squeeze_breakout @ 1h — the faster validated edge
24-bar range in its lowest 20th percentile (volatility squeeze) + close breaks
the 24-bar high/low. Stop = 1× range, exit = stop or 24h time-stop, + SMA200
trend filter.

| metric (real 1h, 3 yr, 26 OOS windows, filtered) | value |
|---|---|
| net Exp-R | **+0.088** |
| PF | 1.12 |
| MaxDD @2% | 32% (≈24% at 1.5% risk) |
| DSR | +1.58 |
| harness | **ACCEPTED** |

Character: ~2.5–3 trades/day fleet-wide, 48→24h holds. Also dies below 1h
(15m −0.11R, 30m −0.05R).

### 4c. Carry (funding harvest) — real but slow
Spot-long + perp-short delta-neutral, cross-margin, universe of 5. Full
realized-funding history (2019–2026).

| window | annual on capital | NW t | maxDD | holdout |
|---|---|---|---|---|
| Full 2019–26 | +6.5…8.2% | 10.7–15.3 | <3% | PASS |
| Recent 2023+ | +3.9…4.7% | 12.3–17.5 | <1% | PASS |

Character: low-volatility single-digit annual at 3× — NOT fast money, does not
compound to daily-percent targets. Not yet built into the engine (config-only
executor pending).

## 5. Engineering delivered

- **squeeze_breakout + donchian_trend** as engine strategy profiles (faithful
  ports, config-gated, parity preserved, ~40 dedicated tests).
- **Multi-strategy mode** (`STRATEGIES` env): several validated edges on ONE
  shared account — one balance / kill switch / profit lock / slot pool — each
  entering on its own timeframe and exiting by its own rule. One position per
  symbol enforced across strategies. This is the deployed "two friendly
  systems on one line" (donchian 4h + squeeze 1h).
- **Stage-3 live order adapter** (`live_orders.py`): real entry+SL/TP
  placement with partial-fill accumulation, timeout/retry, reconciliation,
  emergency stop — behind a FIVE-gate lock (`LIVE_ENABLED` +
  `LIVE_HUMAN_CONFIRM` + live mode + `LIVE_SEND_ORDERS` + keys). Every default
  OFF; without an armed adapter it is a SIMULATED stub.
- **Risk rails**: 10% daily loss kill switch + 10% daily profit lock, both
  scaling with live balance; exposure cap; per-symbol cooldown.
- Dashboard (mode-aware, HTTP Basic auth), Telegram commander, ~654 tests green.

## 6. Live status & the universe-drift lesson (current)

Running paper, multi-strategy (donchian 4h + squeeze 1h), shared 200 USDT.
Early run showed an all-long loss cluster. Diagnosis from live `/signals`:
- No bug — both directions generated; every trade stopped cleanly at −1R.
- ~95% of signals rejected by the exposure cap → only ~2 concurrent positions
  (low diversification, high variance).
- **Critically, the live scanner (top-40 by volume) was trading EXOTIC coins
  (WLD, CL, XAG, SPCX) that were never in the validation set** — their
  breakouts fail far more. Trading off the validated universe.
- Fix (config): pin `UNIVERSE_INCLUDE` to the 12 validated coins
  (BTC/ETH/SOL/BNB/XRP + DOGE/ADA/AVAX/LINK/TON/TRX/DOT), lower `RISK_PCT` to
  ~1.5 for diversification under the exposure cap, fresh epoch.

**Discipline note:** every strategy change is validated on real data before
paper, and NO parameter is tuned to a handful of live trades (that is the
overfitting trap the whole methodology exists to avoid). A validated edge
still needs 30–50 live trades before its expectancy is judged.

## 7. Honest bottom line

- One strong edge (donchian 4h), one solid faster edge (squeeze 1h), one slow
  real edge (carry). All swing/positional — **fast directional scalping has no
  measured net edge on this instrument** across 20+ cells and all timeframes
  down to 5m.
- The engineering (multi-strategy, live lock, risk rails) is production-grade.
- No returns are guaranteed; the edges are real in-sample+OOS but modest, and
  live is paper until evidence accumulates.

## 8. Open research directions (not yet done)

- Scalp tactics used by real discretionary/copy traders NOT yet tested on this
  data: **liquidity-sweep / stop-hunt reversal (ICT/SMC)**, **VWAP reversion**,
  **opening-range breakout**, **break-and-retest**, **RSI2 pure
  mean-reversion**, **session/time-of-day effects**. (Order-flow / L2-imbalance
  scalping is NOT testable here — only OHLCV is available, no tick/L2 data.)
- Carry paper executor (cross-margin, universe 5).
- Regime overlay for donchian (only if it survives its own holdout — no
  post-hoc curve-fitting).

*This dossier is regenerable; all experiments live in `scripts/` and the
`data.binance.vision` cache builder. Test floor: ~654 green.*

---

## 9. Scalp hunt — definitive NO-GO (Phase-3, real-trader tactics)

Tested the canonical pro/copy-trader scalp tactics on real 15m/5m data,
split-half holdout, realistic taker cost:

| tactic | holdout R | verdict |
|---|---|---|
| Liquidity-sweep / stop-hunt reversal (ICT/SMC) | −0.38R | FAIL |
| VWAP reversion | −0.27R | FAIL |
| RSI2 pure mean-reversion (Connors) | −0.19R | FAIL |
| Opening-range breakout | −0.30R | FAIL |
| Momentum continuation (+ trailing) | −0.40R (15m) / −0.73R (5m) | FAIL |

Across ALL waves: ~10 families, 50+ cells of short-TF scalping, every one
net-negative after cost, worsening as the timeframe shortens. Taker
round-trip cost (~0.14%) exceeds the scalp-sized edge. Scalp would need maker
execution (adverse selection — tested, worse) or L2/order-flow data +
low-latency infra (unavailable). **Scalp is NOT viable here.** The validated
positive edges are all swing/positional (donchian 4h, squeeze 1h, carry).

---

## 10. Universe expansion study — the edge is coin-specific (Phase-4)

Owner concern: 12 coins is too few / too few trades. Tested whether donchian
generalises to 15 more liquid, established perps (LTC, BCH, ETC, ATOM, NEAR,
FIL, UNI, AAVE, ARB, OP, INJ, APT, SUI, LDO, ICP), per-coin net-R, taker cost.

**Finding: the edge does NOT generalise to arbitrary liquid coins.** Most of
the 15 were weak or net-negative (LTC −0.13, ETC −0.07, FIL −0.11, INJ −0.11,
AAVE −0.03, APT −0.05, LDO −0.10). Only a handful lean positive. The donchian
trend-breakout edge lives in coins that actually TREND — "boring" large-caps
chop and don't reward breakouts.

Best-5 positive expansion (NEAR, ARB, SUI, ICP, ATOM) as a diversified GROUP:
**meanR +0.213, t +2.12, n=610** — significant. Adding them:

| universe | meanR | t | n |
|---|---|---|---|
| Original 12 | +0.360 | +4.34 | 2,812 |
| **Expanded 17** (+NEAR,ARB,SUI,ICP,ATOM) | **+0.334** | **+4.74** | 3,422 |

**Recommendation: expand to the validated 17-coin universe** — keeps the edge
strong, adds ~22% more trades. This is the honest frequency ceiling: beyond
these 17, adding coins means trading where the edge does NOT exist (dilutes /
loses). More trade frequency must come from the squeeze @1h leg, not from
diluting donchian with edgeless coins.

Validated 17-coin `UNIVERSE_INCLUDE`:
BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,TON,TRX,DOT,NEAR,ARB,SUI,ICP,ATOM

---

## 11. Frequency-optimization campaign (Phase-5) — the frontier is mapped

Owner: maximise frequency AND yield, push limits. Swept squeeze and donchian
parameters toward MORE trades on the 17-coin universe, split-half holdout,
measuring net-R, t, AND trades/day.

**Squeeze — cannot be pushed:** loosening the percentile (Q 20→50) raises
trades (5→9/day) but the edge DIES on holdout (H12 holds strongly negative;
looser Q holdout t<0.8). Best remains the deployed 24/Q20/H24 (~3/day). No
free frequency.

**Donchian — robust; a real frequency/yield frontier (all cells PASS holdout
t 2.2–2.9):**

| cell (N,X) | trades/day | R/trade | daily-R (yield) |
|---|---|---|---|
| N30/X20 | 1.3 | +0.283 | **0.368** (max yield) |
| N20/X20 (deployed) | 1.4 | +0.252 | 0.353 |
| N10/X20 | 1.6 | +0.207 | 0.331 (best freq/yield balance) |
| N10/X10 | **2.2** (max freq) | +0.119 | 0.262 |

**Finding: more frequency costs yield** — a faster exit (X=10) raises trades
+57% but cuts total yield −26%. The deployed config sits near the yield-optimal
frontier. Optional frequency bump: N10/X20 (`DON_ENTRY_BARS=10`) gives +14%
trades at ~94% of the yield — a defensible "more action" choice, still
validated.

**Combined validated ceiling (17 coins):** donchian ~1.4–2/day + squeeze
~3/day ≈ **~4.5–5 trades/day**. Beyond this, more frequency requires either
edgeless coins (proven loss), edge-killing looseness (proven), or scalp
(proven dead across 10 families). The directional-frequency frontier is now
fully mapped. Genuinely MORE activity with positive edge must come from a
DIFFERENT edge (carry — uncorrelated funding harvest), not from pushing the
directional edges past their limits.

---

## 12. Edge-expansion + system wave (2026-07-08, second session wave)

Owner directive: faster data flow, useful Shadow/Friday management, MORE
edge (not more filters). Pre-registered cells, real archive data 2023-07 →
2026-06 (1h/4h, 17 validated + 12 new coins), split-half at 2025-01-01,
taker+slip+funding costs, kill-rule. Campaign trial ledger: 88 → 95.

### Killed (kill-rule, both documented and final)

| cell | H1 | H2 | verdict |
|---|---|---|---|
| donchian @4h on 12 NEW coins (PEPE WIF SEI TIA JUP WLD FET STX IMX ENA ONDO HBAR) | +0.63R (t 2.4) | **−0.02R** | **KILL — edge stays coin-specific (3rd confirmation)** |
| squeeze @1h on expansion-5 + 12 new | +0.055R | **−0.02R** | **KILL — and the expansion-5 are NEGATIVE at 1h** |
| donchian @1d (17) | +1.29R | −0.01R | KILL |
| BTC-SMA200 regime hard-filter on donchian @4h | H2 +0.035 vs baseline +0.029, trades −46% | — | NO IMPROVEMENT — regime stays advisory-only |
| squeeze @2h (17) | +0.066R | +0.071R | WATCH (both halves +, t<2/half; not deployed — TF-correlation stacking) |

### ACCEPTED: squeeze_breakout @4h/1d (ts=24 bars = 96h)

Replication sim: +0.193R, t 4.09, H1 +0.21 / H2 +0.18, 15/17 coins positive
(calibration: the same sim UNDER-reports the known 1h edge, +0.037 vs
+0.088 harness — conservative). Then the REAL walk-forward harness
(offline data_override from the archive, warmup 525, funding charged,
deflated n_trials=95):

| run | net Exp-R | PF | MaxDD @1.5% | DSR | decision |
|---|---|---|---|---|---|
| 5 majors | +0.193 | 1.49 | 15.5% | +2.63 | **ACCEPTED** |
| validated 17 | +0.211 | 1.56 | 9.5% | +3.30 | **ACCEPTED** |

Deployed as the third leg. Combined validated ceiling is now ≈5.5–6
trades/day (donchian 4h ~1.4–2 + squeeze 1h ~3 + squeeze 4h ~1).

### Engineering shipped with this wave

- **Same profile at two TFs** in STRATEGIES (second instance's setup_type =
  "profile@ltf"; models.profile_of() keeps risk/exit profile semantics).
- **Per-strategy universe** (`:u=BTC+ETH+...`): squeeze@1h pinned to its
  validated 12 — it measured NEGATIVE on the donchian-expansion coins.
- **Closed-bar-aware kline cache** + **universe re-rank interval**: per-cycle
  REST calls ~69 → ~17–18 at the deployed config; parity-safe by
  construction (closed bars only change on bar close). Failed refetch serves
  last good cache; stale-entry guard covers the tail risk.
- **SHADOW_READINESS** governor section: explicit activation staircase
  (stage 1 SHADOW_APPLY ≥50 resolved/setup; stage 2 risk modulation only at
  N≥100 AND monotone buckets). Friday stays excluded; the governor report
  is its measured replacement.

### Watch flag (honest)

donchian @4h recent-half softness in the replication sim (2025+ ≈ +0.03R vs
+0.48R in 2023–24; the 5.8y harness validation remains authoritative). The
30–50-trade paper window is exactly the instrument to confirm or refute
this. squeeze@4h is strong in BOTH halves including 2025+.

Test floor: 684 green.

---

## 13. Frequency frontier @4h (wave 3, 2026-07-08) — trials 95 → 99

Owner: "fastest, quickest to profit." Pre-registered cells on the strongest
recent-regime edge (squeeze@4h) + donchian variant revalidation:

| cell | trades/day | R/trade | daily yield | halves | verdict |
|---|---|---|---|---|---|
| squeeze@4h Q20/W24 (deployed) | 0.99 | +0.193 | 0.191 R/d | + / + | **baseline stays — yield-optimal** |
| squeeze@4h **Q30**/W24 | 1.25 (+27%) | +0.130 | 0.162 R/d (85%) | +0.16 / +0.10 | **VALIDATED OPTION** — real harness: net +0.161R, PF 1.43, DD 14%, DSR +2.82 (n_trials=99), ACCEPTED |
| squeeze@4h Q20/**W12** | 1.34 | +0.090 | — | H2 t 1.0 | KILL |
| squeeze@4h on 12 NEW coins | — | — | — | H1-picked 7 coins → H2 +0.088R t 0.89 | **WATCH only** — positive but insignificant; NOT deployed |
| donchian@4h **N10**/X20 | +12% trades | +0.194 | ~93% of N20 | + / + (H2 soft both) | validated option (phase-5 confirmed) |

Pattern (third time measured): **more frequency always costs per-trade edge**;
the deployed baseline sits at the yield optimum. The validated "more action"
package for the owner is `:q=30` on the squeeze@4h leg and/or `:n=10` on the
donchian leg — both harness/holdout-validated, both ~85–93% of max yield.
STRATEGIES specs now support per-leg `:n=` and `:q=` so these flip without
touching global config.

### §13 addendum — universe frontier check for squeeze@4h (trials 99 → 100)

Owner asked whether OTHER assets were researched. The one genuinely untested
gap: the 10 phase-4-rejected liquid coins (LTC BCH ETC FIL UNI AAVE OP INJ
APT LDO) had never seen the newly-validated squeeze@4h. Tested (36mo real 4h,
H1-select/H2-confirm): H1-picked 7-coin group +0.234R (t 2.27) →
**H2 −0.116R (t −1.68) — KILL.** Squeeze@4h is coin-specific exactly like
donchian. Combined with wave-2/3: every liquid Binance USDT-M perp with ≥2y
history outside the validated 17 has now been tested against at least one
validated edge and failed holdout. **The 17-coin universe IS the frontier**;
coins with <18mo history remain untestable by protocol (insufficient split
material), and sub-liquid names fail the spread guard before ever reaching a
signal.

---

## 14. FINAL popular trend-TA wave (2026-07-09) — trials 100 → 111

Owner: "one last deep pass over the popular trend-following TA never tested."
Seven families @4h on the validated 17 (Ichimoku cloud+TK, Heikin-Ashi flip,
MACD histogram cross, Parabolic SAR flip, DMI cross ADX>20, Golden cross
50/200, Bollinger band-ride — each with the SMA200 alignment where popular
usage has it), plus 1h re-checks and 3 overlap cells. Same protocol.

### Raw split-half results

| family @4h | n (/day) | R | H1 / H2 | verdict |
|---|---|---|---|---|
| MACD hist cross | 3,564 (3.3) | +0.091 (t 3.6) | +0.124 / +0.060 | candidate → overlap test |
| Parabolic SAR flip | 3,960 (3.6) | +0.078 (t 3.5) | +0.100 / +0.058 | candidate → overlap test |
| Bollinger band-ride | 2,751 (2.5) | +0.116 (t 3.3) | +0.147 / +0.087 | candidate → overlap test |
| Ichimoku cloud+TK | 2,028 | +0.089 | +0.174 / **+0.015** | WEAK — H2 flat, killed |
| Golden cross 50/200 | 461 | +0.873 | +1.716 / +0.197 (t 1.05) | WEAK — n too small, killed |
| Heikin-Ashi flip | 4,041 | −0.004 | +0.027 / −0.032 | KILL |
| DMI cross ADX>20 | 1,892 | +0.059 | +0.178 / **−0.056** | KILL |
| (all @1h re-checks) | — | — | MACD −0.024 · PSAR −0.036 · Ichimoku −0.044 | KILL — the 4h floor holds |

### The decisive overlap test (marginal value vs the deployed legs)

Are these NEW trades, or the donchian@4h + squeeze@4h trades under another
name? Entry overlap (same symbol+side within ±2 bars) and the edge of the
NON-overlapping remainder:

| family | overlap w/ don+sqz@4h | non-overlap H2 R | verdict |
|---|---|---|---|
| Bollinger band-ride | **50%** | **−0.164 (t −3.9)** | its edge WAS our trades; the rest loses — KILL |
| MACD hist | 14% direct, but 72% shared w/ BAND, 86% w/ PSAR | **−0.005** | incremental trades have no holdout edge — KILL as a leg |
| Parabolic SAR | 11% / one family with MACD (86%) | **+0.001** | same — KILL as a leg |

**Conclusion (final for trend-TA):** the popular trend indicators that
survive split-half at 4h are all measuring the SAME underlying 4h-trend
phenomenon the deployed donchian@4h + squeeze@4h legs already harvest — with
worse per-trade quality. Their incremental (non-overlapping) trades carry
ZERO holdout edge. Adding any of them would duplicate winners we already
take and add pure-noise fills. **The trend-TA inventory is now complete: no
popular family adds a fourth directional leg.** Positive side-finding: three
independent indicator families confirming the same edge is strong evidence
the deployed legs sit near the efficient frontier of what OHLCV trend
signals can extract from these instruments.

Reproducible: `scripts/trend_ta_wave.py` (+ overlap analysis in session log).

---

## 15. Ichimoku deep-dive (2026-07-09, owner-directed) — trials 111 → 121

Owner: "focus on Ichimoku; find the TF/conditions where it is positive."
Bounded pre-registered grid: 10 cells (TK-cross strong / Kijun-cross / cloud
breakout / +chikou / doubled 20-60-120 params × 2h/4h/1d), validated 17,
same protocol. 9 of 10 cells KILL or WEAK. One exceptional survivor:

### I1 TK-cross "strong" @4h — the strongest harness result in the project

Rules: fresh Tenkan(9)×Kijun(26) cross while close is on the matching side
of the displaced cloud; stop 2×ATR; exit on opposite TK cross; no TP.

| stage | result |
|---|---|
| Research sim | +0.253R, t 5.30, H1 +0.344 (t 4.6) / H2 +0.175 (t 2.9), **17/17 coins positive**, 1.7 trades/day |
| Overlap bar | 29% overlap w/ don+sqz@4h; non-overlap H2 +0.046 (t 0.7) — additive edge UNPROVEN |
| **REAL harness @4h/1d ×17** (n_trials=121) | **net +0.314R, PF 1.71, MaxDD 14.7% @1.5%, DSR +4.14, 698 OOS trades — ACCEPTED** |

Regime note: Ichimoku TK-cross H2 (2025+) = +0.175R where donchian's same-
window H2 = +0.03R — it is the strongest recent-regime directional edge
measured on this system.

### Deployment decision (discipline over excitement)

As an ADDITIVE 4th risk leg it fails the marginal-evidence bar (its
non-overlapping trades are unproven — same bar that killed MACD/PSAR/
band-ride). As a STANDALONE system it is harness-ACCEPTED with the best
numbers in the book. Resolution: **ported to the engine as the
`ichimoku_trend` profile (full tests) and deployed SHADOW-ONLY** —
`SHADOW_ONLY_SETUPS=ichimoku_trend` — so it is scored and tracked on live
data, takes ZERO risk, and accumulates the evidence to become donchian's
REPLACEMENT if the paper window confirms donchian's 2025+ softness.
Engine port: detector (setups.py), streaming TKCROSS exit (executors.py,
seeded with pre-entry (high,low) history at decide() time — parity across
paper/backtest/live), risk branches (stop ceiling + no-TP contract),
7 dedicated tests.

Other cells for the ledger: I1@2h KILL (H2 −0.01), I1@1d WEAK, I2 Kijun-
cross @4h WEAK (H2 t 0.6) / @1d KILL, I3 cloud-break @2h non-overlap
NEGATIVE / @1d WEAK, I4 chikou @4h WEAK (H2 t 0.4), I5 doubled @4h KILL /
@1d WEAK. The 4h TK-cross is the only Ichimoku system with real edge here.
