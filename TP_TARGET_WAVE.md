# TP TARGET WAVE — do TP1/TP2 targets earn more?

**Date:** 2026-07-25
**Question (owner):** "Tp1 Tp2 vs aktif mi?" → "Ölç."
**Answer:** They are **not active** on any deployed leg, and measuring proves
they **must not be**. A take-profit raises the win rate and destroys the money.
**TP stays OFF. No config change.**

Harness: `scripts/tp_target_wave.py` (+ `scripts/tp_bandwalk_probe.py`).
Research only — neither script changes engine behaviour.

---

## 1. What is actually deployed today

All four live legs ship with **no reachable take-profit**. `RiskManager._build_targets()`
(`src/aurvex/risk.py:423-439`) returns a single target at `entry ± R × TP_R` with
fraction 1.0 and two zero-fraction placeholders, where `TP_R` is:

| leg | knob | default |
|---|---|---|
| donchian_trend | `DON_TP_R` | 1000.0 |
| squeeze_breakout | `SQZ_TP_R` | 1000.0 |
| ichimoku_trend | `ICH_TP_R` | 1000.0 |
| band_walk | `BW_TP_R` | 1000.0 |

1000R is unreachable by construction, so the three-slot TP contract stays intact
while nothing ever realises at a target. `TP1_FRAC` / `TP2_FRAC` / `TP3_FRAC`
(0.5 / 0.3 / 0.2) exist in config but are **dead for these four legs** — they are
only read by the `bugra_replica` branch. No TP1 also means **no break-even stop
move and no runner logic** on the deployed legs.

Exits today are: the stop, plus the validated rule — streaming channel exit
(donchian), TK-cross (ichimoku), time-stop (squeeze 24 bars, band_walk 12 bars).

## 2. Method

Real `Backtester`, real 4h Binance archive, deployed per-leg config and universe.
The **only** thing varied is that leg's `TP_R`. Baseline = 1000R (= no TP);
cells at 5R / 3R / 2R / 1.5R / 1R, each taking 100% — exactly what the knob does.

Reported per cell: n, net Exp-R (cost-honest, 0.13% taker round-trip charged in
R), **TOTAL R**, win%, MaxDD, and both halves of the sample.

Decision rule, fixed before looking at results: **adopt a TP only if TOTAL R
rises AND both halves stay positive.** A number that only flatters the win rate
is not enough.

## 3. Results

### donchian_trend (12 coins)

| TP | n | netExpR | TOTAL R | win% | maxDD | H1 | H2 |
|---|---|---|---|---|---|---|---|
| **none** | 1233 | **+0.357** | **440.3** | 31.5 | 43.6 | +0.529 | +0.185 |
| 5R | 1568 | +0.110 | 171.9 | 29.4 | 49.5 | +0.158 | +0.061 |
| 3R | 1903 | +0.070 | 133.5 | 31.1 | 62.2 | +0.114 | +0.027 |
| 2R | 2366 | +0.047 | 110.7 | 35.6 | 62.1 | +0.056 | +0.038 |
| 1.5R | 2813 | +0.029 | 81.0 | 41.3 | 83.6 | +0.014 | +0.044 |
| 1R | 3654 | +0.013 | 48.0 | **51.4** | 60.0 | −0.005 | +0.031 |

The clearest result in the wave. A 1R target lifts the win rate 31.5% → 51.4%
and cuts total profit by **89%** (440 R → 48 R). Drawdown gets **worse**
(43.6 → 83.6 at 1.5R): losers still run to the full stop while winners are
capped, so the equity curve loses the tail that used to repair it.

### squeeze_breakout (12 coins)

| TP | n | netExpR | TOTAL R | win% | maxDD | H1 | H2 |
|---|---|---|---|---|---|---|---|
| **none** | 872 | +0.146 | **127.0** | 46.8 | 24.1 | +0.172 | +0.119 |
| 5R | 873 | +0.146 | 127.6 | 46.8 | 30.5 | +0.161 | +0.131 |
| 3R | 882 | +0.143 | 125.8 | 47.2 | 30.1 | +0.171 | +0.114 |
| 2R | 896 | +0.108 | 97.1 | 47.9 | 30.3 | +0.123 | +0.094 |
| 1.5R | 912 | +0.082 | 75.0 | 48.7 | 28.2 | +0.093 | +0.071 |
| 1R | 950 | +0.076 | 72.6 | **53.5** | 24.9 | +0.086 | +0.067 |

The 24-bar time-stop already truncates the tail, so 5R/3R barely bind (+1 R /
−1 R — noise, n moves by 1 and 10 trades). From 2R down the TP starts biting:
−30 R, −52 R, −54 R. Same shape as donchian, smaller amplitude.

### ichimoku_trend (11 coins)

| TP | n | netExpR | TOTAL R | win% | maxDD | H1 | H2 |
|---|---|---|---|---|---|---|---|
| **none** | 1456 | **+0.263** | **383.0** | 38.5 | 32.6 | +0.253 | +0.273 |
| 5R | 1519 | +0.223 | 338.3 | 38.8 | 31.3 | +0.188 | +0.257 |
| 3R | 1609 | +0.183 | 295.0 | 39.5 | 32.6 | +0.150 | +0.216 |
| 2R | 1715 | +0.148 | 253.0 | 41.6 | 31.5 | +0.111 | +0.184 |
| 1.5R | 1795 | +0.132 | 237.7 | 45.4 | 34.5 | +0.102 | +0.163 |
| 1R | 1932 | +0.086 | 166.6 | **52.2** | 37.7 | +0.065 | +0.108 |

Perfectly monotonic: every step tighter costs money, and unlike donchian it does
not even buy a drawdown improvement. −216 R at 1R.

### band_walk (5 majors)

| TP | n | netExpR | TOTAL R | win% | maxDD | H1 | H2 |
|---|---|---|---|---|---|---|---|
| **none** | 1273 | +0.087 | 110.3 | 45.2 | 28.6 | +0.062 | +0.111 |
| 5R | 1289 | +0.088 | 113.7 | 45.2 | 29.6 | +0.053 | +0.123 |
| 3R | 1331 | +0.093 | 123.5 | 45.4 | 26.8 | +0.061 | +0.124 |
| 2R | 1421 | +0.088 | 125.7 | 46.0 | 27.0 | +0.048 | +0.129 |
| 1.5R | 1494 | +0.058 | 87.4 | 46.9 | 28.7 | +0.028 | +0.089 |
| 1R | 1644 | +0.040 | 66.3 | **51.8** | 41.1 | +0.013 | +0.068 |

The one leg that superficially passes the rule: +13 R at 3R, +15 R at 2R, both
halves positive. Section 5 tests whether that is an edge. It is not.

## 4. Portfolio view — the number that matters

Summing the four legs on the same data:

| TP | TOTAL R | vs baseline | portfolio win% |
|---|---|---|---|
| **none** | **1060.6** | — | 40.0 |
| 5R | 751.5 | −29% | 38.9 |
| 3R | 677.8 | −36% | 39.3 |
| 2R | 586.5 | −45% | 41.2 |
| 1.5R | 481.1 | −55% | 44.5 |
| 1R | 353.5 | **−67%** | **51.9** |

This is the whole finding in one table. A 1R take-profit turns a 40%-win system
into a 52%-win system **and throws away two thirds of the profit.** It would feel
dramatically better to watch and pay a third as much.

## 5. Is band_walk's +15 R real? No — it is trade count, not edge

Total R can rise for two different reasons: the trades got better (per-trade
Exp-R rises → real edge), or there are simply more of them at the same
expectancy, because closing early frees a slot sooner (arithmetic).

`scripts/tp_bandwalk_probe.py` separates them with a Welch t-test on per-trade R:

| TP | n | mean R | sd | SE | total R | t vs baseline |
|---|---|---|---|---|---|---|
| none | 1273 | +0.087 | 1.281 | 0.036 | 110.3 | — |
| 3R | 1331 | +0.093 | 1.177 | 0.032 | 123.5 | **0.13** |
| 2R | 1421 | +0.088 | 1.088 | 0.029 | 125.7 | **0.04** |

Three independent reasons this does not transfer to production:

1. **The per-trade edge is flat.** t = 0.13 (3R) and t = 0.04 (2R) against a
   ~2.0 threshold. The 2R cell's mean is +0.088 vs a baseline +0.087 — a
   difference of 1/36th of one standard error. There is no per-trade
   improvement here to adopt; the trades did not get better.
2. **The extra trades are not band_walk's to keep.** The gain comes almost
   entirely from n rising (1273 → 1421 at 2R, +12%) because a closed position
   frees a slot. In the deployed system the four legs share **one** 8-slot pool
   on one account, so a freed slot is at least as likely to go to donchian
   (+0.357 Exp-R) as to another band_walk entry (+0.087). Isolated-leg trade
   count does not survive the shared-slot portfolio.
3. **The first half gets worse.** Baseline H1 +0.062 → +0.048 at 2R. The
   "improvement" lives entirely in H2. That is a coin flip presented as a result.

Adopting a 2R TP on band_walk would therefore trade a statistically
indistinguishable per-trade change for a real, measured **−450 R** across the
other three legs. Rejected.

## 6. Verdict

**No TP level clears the bar on any leg.** TP stays OFF — `DON_TP_R`,
`SQZ_TP_R`, `ICH_TP_R`, `BW_TP_R` remain 1000.0. `TP1_FRAC`/`TP2_FRAC`/`TP3_FRAC`
remain dead for the deployed legs, and there is no break-even move and no runner.

This independently confirms the record in `SYSTEM_STATE.md:162` — 13 exit
variants measured 2026-07-08, all destroying yield. Those varied exit *rules*;
this wave isolates the take-profit *level* alone, across all four deployed legs,
and reaches the same conclusion by a different route.

### Why, mechanically

These are trend-continuation legs. Their expectancy lives in a thin right tail:
~31–46% of trades win, and the few that run many R pay for all the losers. A
take-profit is a tail amputation. It is symmetric on the upside only — the stop
distance never shrinks to match — so every R of capped upside is a permanent
transfer out of the edge. The win rate rises because you convert
would-be-large-winners into certain-small-winners; the money falls because the
large winners were the entire business.

### The trap this closes

The win rate is the most emotionally persuasive number on the dashboard and the
least informative. Every TP cell in this wave improves it. Every TP cell in this
wave loses money. If a future change is ever justified by "the win rate went up,"
this document is the reason to ask for total R before believing it.

## 7. Reproduce

    python scripts/tp_target_wave.py
    python scripts/tp_bandwalk_probe.py
