# AurvexAI — Positive & Serial Edge Mission Report

**Date:** 2026-07-08 · **Harness:** `scripts/edge_search_master.py` · **Live:** OFF
(unchanged) · **Trading route:** disabled · **Data route:** public archive only.

This report answers the mission "find the best measured, robust, net-positive,
as-frequent-as-possible, paper-ready model" — with the full battery (net of
fee+slippage+funding, gross/net split, split-half + out-of-symbol holdout, DSR
multiple-trial deflation, MaxDD, trades/day, R/day, concentration) and honest
GO/NO-GO verdicts.

---

## 1. Headline

The formal harness **discovered a materially better model than anything
previously deployed**: the **volume-confirmed 1h momentum breakout** — the
existing 1h donchian with a volume-expansion quality gate (breakout bar volume
> k × median of the prior 50 bars).

**Best positive + serial + PROVEN model → `volexp2.5-donch 1h`:**

| metric | value |
|---|---|
| net Exp-R (after fee+slip+funding) | **+0.394R / trade** |
| Profit Factor | **1.60** |
| DSR (deflated across all trials) | **0.95** (PASS) |
| trades/day (28-coin fleet) | **~3.0** |
| R/day (fleet) | **+1.19R** |
| split-half holdout H2 | +0.470R |
| out-of-symbol (test coins) | +0.424R |
| max single-coin share of R | 0.11 (well diversified) |
| n | 3297 |
| **verdict** | **ACCEPTED_FOR_PAPER** |

This more than **triples** the plain 1h donchian's net edge (+0.12 → +0.39R) and
raises PF 1.17 → 1.60, while staying serial (~3 trades/day). The volume filter
keeps participation-confirmed breakouts and drops low-volume fakeouts. It is
causal (signal-bar volume is known at decision time — no lookahead).

---

## 2. Full leaderboard (net of fee+slip+funding, DSR-deflated)

Ranked: ACCEPTED first, then by R/day.

| candidate | tf | verdict | netExpR | PF | DSR | t/day | R/day | maxDD(R) | H2R | OOSte | maxcoin | n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| volexp2.5-donch | 1h | **ACCEPTED** | +0.394 | 1.60 | 0.95 | 3.01 | +1.19 | 118 | +0.470 | +0.424 | 0.11 | 3297 |
| volexp3.0-donch | 1h | **ACCEPTED** | +0.412 | 1.64 | 0.99 | 2.17 | +0.89 | 87 | +0.499 | +0.385 | 0.15 | 2369 |
| volexp2.0-donch | 4h | **ACCEPTED** | +0.857 | 2.35 | 1.00 | 0.30 | +0.26 | 30 | +0.492 | +1.063 | 0.22 | 711 |
| volexp1.5-donch | 1h | RESEARCH_ONLY | +0.219 | 1.32 | 0.00 | 5.86 | +1.29 | 231 | +0.175 | +0.238 | 0.09 | 6422 |
| PF: volexp1h+squeeze1h | mix | RESEARCH_ONLY | +0.241 | 1.39 | 0.15 | 5.21 | +1.26 | 180 | +0.242 | +0.280 | 0.09 | 5703 |
| volexp2.0-donch | 1h | RESEARCH_ONLY | +0.287 | 1.43 | 0.38 | 4.21 | +1.21 | 181 | +0.293 | +0.320 | 0.10 | 4612 |
| PF: donchian1h+squeeze1h | mix | RESEARCH_ONLY | +0.114 | 1.17 | 0.00 | 9.96 | +1.14 | 286 | +0.079 | +0.126 | 0.08 | 10911 |
| donchian N48/X20 | 1h | RESEARCH_ONLY | +0.122 | 1.17 | 0.00 | 8.96 | +1.09 | 294 | +0.083 | +0.131 | 0.08 | 9820 |
| donchian N30/X20 | 1h | RESEARCH_ONLY | +0.082 | 1.12 | 0.00 | 10.71 | +0.88 | 346 | +0.047 | +0.084 | 0.10 | 11732 |
| donchian N20/X20 | 4h | RESEARCH_ONLY | +0.361 | 1.52 | 0.25 | 1.10 | +0.40 | 131 | +0.219 | +0.338 | 0.15 | 2599 |
| donchian N20/X10 | 2h | RESEARCH_ONLY | +0.104 | 1.17 | 0.03 | 2.97 | +0.31 | 150 | +0.036 | +0.093 | 0.19 | 3231 |
| squeeze W24 p20 | 30m | RESEARCH_ONLY | +0.059 | 1.16 | 0.14 | 0.86 | +0.05 | 18 | +0.071 | +0.086 | 0.39 | 940 |
| squeeze W24 p20 | 1h | RESEARCH_ONLY | +0.047 | 1.13 | 0.07 | 1.03 | +0.05 | 63 | +0.045 | +0.069 | 0.12 | 1091 |
| donchian N48/X20 | 30m | **NO_GO** | −0.012 | 0.98 | 0.00 | 7.69 | −0.10 | 329 | −0.012 | −0.040 | 0.33 | 8442 |
| squeeze W24 p20 | 15m | **NO_GO** | −0.065 | 0.85 | 0.00 | 2.25 | −0.15 | 161 | −0.065 | −0.033 | 0.38 | 2468 |

### How to read it
- **DSR is the multiple-testing filter.** Plain donchian is net-positive and
  holdout-positive, but its Sharpe is not distinguishable from the *best-of-K*
  under the null across the trials run → DSR 0.00 → correctly RESEARCH_ONLY, not
  paper-ready on its own. Only the volume-confirmed cells clear it. (DSR here is
  conservative because the trials are correlated same-family cells.)
- **The frequency/quality frontier is explicit inside the volexp family:** lower
  k = more trades, higher R/day, but lower per-trade edge and DSR; higher k =
  fewer, higher-quality, DSR-passing trades. **k=2.5 is the knee** — near-max
  R/day (+1.19) AND DSR-pass.

---

## 3. Per-strategy validation verdicts

| strategy | status | evidence |
|---|---|---|
| **volexp donchian 1h (k≥2.5)** | **ACCEPTED_FOR_PAPER** | net +0.39R, PF 1.60, DSR 0.95, holdout + OOS both strong, diversified |
| donchian 4h/1d (unfiltered) | RESEARCH_ONLY | net +0.36R but DSR 0.25 (thin sample / slow); strong but not deflation-proof alone |
| donchian 1h (unfiltered) | RESEARCH_ONLY | net +0.12R, holdout-positive, but DSR 0.00 after deflation |
| squeeze_breakout 1h/4h | RESEARCH_ONLY | net +0.05R, marginal; positive but low PF, low DSR |
| squeeze 15m/30m, donchian 30m | **NO_GO** | net ≤ 0 / PF ≤ 1 — cost eats the sub-1h move |
| 5m/15m directional scalp | **NO_GO** (prior waves + reconfirmed) | net-negative every family; 1h is the cost floor |
| mean-reversion (5m/15m/4h) | **NO_GO** | net-negative every TF — crypto trends, doesn't revert |
| maker-MR, lead-lag, Keltner, pyramiding | **NO_GO** | net-negative on holdout (EDGE_SEARCH Phase 6) |
| funding/basis carry | NEEDS_MORE_DATA (as executable sleeve) | +~4%/yr structural, uncorrelated, but slow and executor not built |

---

## 4. Universe

Strategy-specific, edge-producing coins only (not padded for trade count). The
1h momentum universe is the 28-coin set screened in EDGE_SEARCH Phase 6d/6f
(each holdout-positive + sign-consistent; 11 of 31 non-core candidates passed).
The volexp filter is applied ON TOP of this universe; concentration stays low
(max single-coin R share 0.11 at k=2.5), so no single coin carries the edge.

---

## 5. Risk / sizing (already retuned, EDGE_SEARCH Phase 6g)

Realized frequency ≠ backtest frequency: with too few slots the edge
adverse-selects to NEGATIVE. `aggressive_paper` was retuned to
**200 / 1% / 0.75–1.5 band / 12 slots / 800% exposure / 10% daily kill** — the
minimum slot count at which the edge survives, with per-trade risk lowered so 12
slots stay ≤12% concurrent under the kill switch. Config-only; `decide()`
untouched; parity intact.

---

## 6. Data / connection posture

- **Data route (allowed):** public `data.binance.vision` archive (OHLCV, 5m→1d,
  ~48 coins, 2.2–2.5 yr). fapi is geo-blocked (451) from the runner; the archive
  is the geo-block-proof source.
- **Trading route (disabled):** no real orders, live executor locked behind the
  five-gate lock, `LIVE_ENABLED=false`. No secrets in code, git, logs or
  dashboard. Unchanged by this mission.

---

## 7. Recommended active paper profile

```
STRATEGIES="donchian_trend@1h/4h:en=48:ch=20:atr=2.0:vk=2.5 donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
UNIVERSE_INCLUDE=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,ATOM/USDT:USDT,ENA/USDT:USDT,FET/USDT:USDT,GALA/USDT:USDT,GRT/USDT:USDT,JUP/USDT:USDT,SEI/USDT:USDT,STX/USDT:USDT,UNI/USDT:USDT,WIF/USDT:USDT,WLD/USDT:USDT,XLM/USDT:USDT
```

The primary sleeve is the ACCEPTED volume-confirmed 1h momentum (`:vk=2.5`); the
4h donchian and 1h squeeze ride along as RESEARCH_ONLY diversifiers on the same
account (they do not dilute — they add uncorrelated, lower-frequency activity).

---

## 8. Status flags

- **Best positive model:** volexp2.0-donch **4h** (net +0.86R, PF 2.35, DSR 1.00) — highest quality, but slow (0.3/day).
- **Best positive + FREQUENT model:** **volexp2.5-donch 1h** (net +0.39R, PF 1.60, DSR 0.95, ~3/day, R/day +1.19) — the recommended primary.
- **Scalp (<1h directional):** **NO_GO** — reconfirmed net-negative; 1h is the mathematical cost floor.
- **Donchian:** validated (unfiltered RESEARCH_ONLY; **volume-confirmed ACCEPTED**).
- **Squeeze:** RESEARCH_ONLY (marginal).
- **Carry:** structural-positive, NEEDS_MORE_DATA as an executable sleeve.
- **PAPER_READY: YES** — for the volume-confirmed 1h momentum sleeve (ACCEPTED, all cuts pass).
- **LIVE_READY: NO** — by design; forward-test on paper first, live route stays locked.

---

## 9. What changed in the repo (this mission)

- `scripts/edge_search_master.py` — the harness (families × universe × TF × cost;
  net/gross, PF, DSR, MaxDD, trades/day, R/day, holdout, OOS, verdicts).
- `src/aurvex/setups.py` + `config.py` — volume-expansion gate on the donchian
  detector (`DON_VOL_FILTER`/`DON_VOL_K`/`DON_VOL_WINDOW`), opt-in per strategy
  via the `:vk=` STRATEGIES option. Default OFF → parity preserved.
- Tests: `test_edge_search_master.py` (verdict/DSR/net-cost), donchian
  volume-gate + `:vk=` spec tests. Full suite green (663).

**Next honest step:** run the recommended profile on live *paper* for several
days, watch the `/api/brain` panel + realized vs backtest R/day, and only then
consider anything beyond paper.
