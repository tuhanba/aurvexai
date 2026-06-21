# Scalp Strategy Specification

Five setup families, evaluated in **priority order** (first match wins per
symbol per cycle). All operate on a **1m** trigger timeframe (LTF) with **15m**
context (HTF). Every detector returns a `Signal` with normalised `factors`
(0..1) that the score builder turns into a 0–100 score; the structure-based
`stop_hint` feeds the risk manager.

Common context (`Context`, built once per symbol):
- LTF indicators: EMA20/EMA50, RSI(14), ATR(14), ADX(14), rolling highs/lows.
- **HTF bias** ∈ {−1, 0, +1} from the 15m EMA20 vs EMA50 relationship.
- ATR is used to size stop buffers so they scale with each coin's volatility.

Scoring weights per setup live in `scoring.py` (`SETUP_WEIGHTS`). Final score =
70% factor blend + 30% base confidence, then small order-book imbalance (±3) and
spread-tightness (0..+2) adjustments, clamped to 0–100.

---

## 1. Momentum breakout

**Idea.** Price breaks a 20-bar high/low with volume expansion, aligned with HTF.

- **Entry.** Close beyond prior 20-bar extreme by an ATR buffer (`0.10×ATR`),
  with `volume ≥ 1.3×` the 20-bar average and HTF bias not opposing.
- **Stop.** Just beyond the broken level / last candle extreme, minus `0.5×ATR`.
- **TP.** Risk-manager R multiples (1.5R / 2.5R / 4.0R), scaled out 50/30/20.
- **Works when.** Trending / expanding volatility, news-driven impulses.
- **Fails when.** Chop and false breakouts; the volume + ATR-buffer + HTF gate
  exist to suppress those.
- **Risk.** Standard (0.5%/trade). Tighter stop than mean reversion.
- **Metric.** Breakout win-rate and average R by symbol; false-breakout rate
  (TP1 never hit before SL).

## 2. Liquidity sweep / stop-hunt reversal

**Idea.** A wick takes out a swing extreme then closes back inside — a trapped-
liquidity reversal.

- **Entry.** Bullish: low pierces the 20-bar swing low but the candle closes back
  above it and closes up, RSI < 45, `volume ≥ 1.2×` avg. Bearish is the mirror
  (RSI > 55).
- **Stop.** Beyond the sweep wick (`±0.25×ATR`) — i.e. beyond the trap.
- **TP.** R multiples as above.
- **Works when.** Range edges, obvious stop pools, liquidity grabs.
- **Fails when.** Strong trend continuation (the "sweep" is real breakout). A
  `counter_trend_risk` factor down-weights sweeps against HTF bias.
- **Risk.** Standard, but counter-trend entries score lower → fewer taken.
- **Metric.** Reversal follow-through rate; performance split by with-trend vs
  counter-trend.

## 3. Volume expansion continuation

**Idea.** An established LTF trend (ADX) pulls back to EMA20 then resumes on a
volume surge, with HTF agreement.

- **Entry.** `ADX ≥ 20` and HTF agrees; recent pullback touched EMA20; current
  close expands in the trend direction with `volume ≥ 1.5×` avg.
- **Stop.** Beyond the recent pullback swing (`±0.3×ATR`).
- **TP.** R multiples as above.
- **Works when.** Healthy directional trends with rhythmic pullbacks.
- **Fails when.** Range / low-ADX regimes (gated out by `ADX ≥ 20`).
- **Risk.** Standard.
- **Metric.** Continuation win-rate; average R in ADX≥20 regimes.

## 4. Short-term trend continuation (pullback to EMA)

**Idea.** Lower-risk pullback entry: HTF up, LTF EMA20 > EMA50, price dips into
EMA20 and prints a reversal close.

- **Entry.** HTF up + EMA stack up + low touches EMA20 zone + bullish close above
  EMA20 (mirror for shorts).
- **Stop.** Below the pullback low / EMA50 (`−0.3×ATR`); structurally tighter.
- **TP.** R multiples as above.
- **Works when.** Clean trends with shallow pullbacks.
- **Fails when.** Trend exhaustion / regime change; HTF gate and EMA stack reduce
  these.
- **Risk.** Standard; often the best R/R because the stop is tight.
- **Metric.** Pullback win-rate; expectancy vs setup #3 (overlap analysis).

## 5. Mean reversion (extreme conditions only)

**Idea.** In a **non-trending** regime, fade a statistically extreme excursion.

- **Hard gate.** `ADX < 20` (skipped entirely in a trend — mean reversion in a
  trend gets run over).
- **Entry.** Long: price ≥ 2.3 std-dev **below** EMA20, RSI ≤ 22, bullish
  rejection close. Short: ≥ 2.3 std-dev **above**, RSI ≥ 78, bearish close.
- **Stop.** Beyond the rejection extreme (`±0.4×ATR`) — widest of the five.
- **TP.** R multiples as above (often TP1/TP2 do the work).
- **Works when.** Range-bound, low-ADX, over-extended flushes.
- **Fails when.** Trend days — hence the ADX gate and the extreme thresholds.
- **Risk.** Standard risk %, but the wider stop yields a smaller position; the
  lowest base confidence (0.45) of the five.
- **Metric.** Fade win-rate strictly within ADX<20; max adverse excursion.

---

## Exits (all setups)

Managed by the shared `simulate_fill`:
- **Scale-out**: 50% at TP1 (1.5R), 30% at TP2 (2.5R), 20% at TP3 (4.0R).
- **Breakeven**: after TP1 fills, the stop moves to entry (a later stop-out is
  recorded as `BE`, not `SL`).
- **Pessimistic intrabar**: if a bar touches both the stop and a target, the
  **stop** is assumed first. This keeps paper and backtest honest (no optimistic
  fills).

All R multiples, fractions and ATR buffers are config-driven (`.env`), so the
strategy can be tuned without code changes. None of these setups is assumed
profitable yet — that is exactly what paper/shadow/backtest are for (see
[`ROADMAP.md`](ROADMAP.md)).
