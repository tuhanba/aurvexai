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
