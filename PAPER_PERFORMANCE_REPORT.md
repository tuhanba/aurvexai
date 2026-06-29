# PAPER_PERFORMANCE_REPORT.md — Edge Decomposition wave, final verdict

**Date:** 2026-06-29
**Data:** real Binance USDT-M candles, 5 majors (BTC, ETH, SOL, BNB, XRP),
walk-forward OOS, net of fee + slippage + funding (0.045% taker / 0.02% slip /
0.01%-per-8h funding). All paper; `LIVE_ENABLED=false` throughout.

## Verdict (go / no-go)

**NO-GO. No configuration cleared the Acceptance Bar.** Directional 5m/15m
technical analysis does not carry a robust, net-positive, broad edge on these
instruments. The single positive cell (bugra 15m/4h) is **noise concentrated in
one symbol (BNB)** — it is net-negative on the train symbols, flips sign between
runs, and has DSR ≤ 0. Per the wave's pre-committed **Kill Rule**, the
recommendation is a **structural pivot to funding/basis carry**, not further
parameter tuning of directional TA.

This is the honest outcome the wave explicitly allowed for.

---

## Evidence

### Phase 2 — gross vs net decomposition (5m, real)
| strategy | n | gExp-R (gross) | Exp-R (net) | cost_drag | verdict |
|---|---|---|---|---|---|
| bugra_replica | 83 | **−0.0827** | −0.1175 | 0.035 | **no-alpha (dead)** — gross < 0 |
| reversion_v1 | 58 | **+0.0715** | −0.0163 | 0.088 | **cost-killed** — real gross edge, eaten by cost |

The decomposition did its job: it separated a *dead* strategy (bugra 5m, gross
negative) from a *cost-killed* one (reversion 5m, gross positive). Reversion's
cost drag ≈ 0.088R = round-trip cost (0.13%) / fixed stop (1.5%), and is
**timeframe-independent** (0.088 on 5m, 0.090 on 15m) because the stop is a fixed
percent — so higher timeframe cannot fix reversion's cost ratio. Only cheaper
execution can.

### Phase 4A — maker-fill experiment (reversion, conservative fills, real)
| tf | taker net | maker net | fill ratio | adverse_R | verdict |
|---|---|---|---|---|---|
| 5m | −0.133 | **−0.154** | 0.91 | **+0.48** | maker hurts (skips the winners) |
| 15m | −0.052 | **+0.0019** | 0.93 | +0.29 | barely positive, **concentrated** (BTC +0.118, SOL +0.054; BNB −0.137, ETH −0.053) |

Maker flips reversion *marginally* positive only on 15m, and only on 2 of 4
symbols — not a robust edge. On 5m maker actively hurts (high adverse selection:
the missed signals were the winners).

### Phase 4B — higher-timeframe trend sweep (real, DSR deflated across 10 cells)
| combo | profile | n | gExp-R | net Exp-R | PF | MaxDD | DSR | bar |
|---|---|---|---|---|---|---|---|---|
| 15m/4h | bugra_replica | 271 | +0.059 | +0.023 | 1.14 | 18% | +0.68 | 5/5 (initially) |
| 15m/1h | bugra_replica | 336 | +0.020 | −0.017 | 0.94 | 42% | −0.65 | 1/5 |
| 30m/2h | bugra_replica | 731 | −0.014 | −0.049 | 0.83 | 107% | −2.34 | 1/5 |
| 15m/1h–30m/2h | aurvex_enhanced | 650–1007 | ≤0 | −0.14…−0.19 | 0.7 | **144–244%** | ≤−3.8 | 1/5 |

`aurvex_enhanced` (ATR stop) is catastrophic on higher TF (MaxDD 144–244%) — the
fixed-percent stop (bugra) is the only survivable trend exit. `bugra 15m/4h` was
the lone cell that initially flagged 5/5.

### Acceptance-Bar validation of the lone candidate — bugra 15m/4h
Re-run on real data, the candidate **fails every robustness gate**:

| criterion | result | pass |
|---|---|---|
| net Exp-R > 0 | −0.0002 (runs gave +0.062 → +0.023 → −0.0002 — sign-unstable) | ❌ |
| out-of-symbol holdout | TRAIN (BTC+ETH+SOL) **−0.027**; HOLDOUT (BNB+XRP) +0.109 | ❌ |
| not concentrated | per-symbol net+: **2/5** (BNB +0.109 @80% win; BTC −0.094, SOL −0.043 neg; XRP 0 trades) | ❌ |
| DSR > 0 | −0.007 | ❌ |
| PF > 1.1 | 1.03 | ❌ |
| MaxDD < 25–30% | 24.4% | ✓ |
| ≥ 200–300 trades | 275 | ✓ |

**By exit reason (bugra 15m/4h, n=275):** BE 162 (+0.235), TP3 34 (+0.503),
SL 48 (−1.010), MANUAL 31 (−0.218). The 48 stop-outs (−48R) cancel the entire
winner stack — a break-even system that goes negative once cost is charged.

**Conclusion:** the "edge" lives entirely in BNB and does not generalise. It is
not tradeable.

---

## Why this is a real finding, not a measurement artifact

Phase 0 fixed the two bugs that would have corrupted this analysis:
- **close_time stamping (F3):** hold-length/AvgBars were a wall-clock artifact;
  now correct.
- **gross/net separation (F2):** every trade carries `R_gross` and `R_net`,
  reconciled to the cent (`gross − fees − funding == net`), so cost-killed vs
  no-alpha is provable, not guessed.

The decomposition, maker model (conservative through-fills only), sweep
(DSR-deflated for multiple testing), and out-of-symbol holdout are all committed,
tested (504 passing, nothing skipped), and reproducible on the engine host.

---

## Recommendation — Kill Rule pivot: funding / basis carry

Directional TA is not the edge. The next wave should test a **persistent,
documented** perp edge instead of price prediction:

1. **Funding carry** — when 8h funding is richly positive, shorts are *paid* to
   hold; delta-hedge (short perp vs spot/another venue) to harvest funding with
   minimal directional risk. The premium is structural, not a forecast.
2. **Basis carry** — perp-vs-spot (or quarterly) basis as a mean-reverting,
   fundable spread.

These have edge that does not depend on calling 15m candle direction, which this
wave has shown the system cannot do profitably net of cost. Sizing/leverage stays
frozen until a carry config clears the same Acceptance Bar.

**Until then: no live, no risk increase, no promotion to paper of any directional
config.** The directional engine remains paper/observe-only.

---

## Artifacts (reproducible on the engine host)
`AUDIT_FINDINGS.md`, `scripts/decompose_edge.py` → `trade_ledger.csv` +
`decomposition_report.md`, `scripts/maker_experiment.py` →
`execution_experiments_report.md`, `scripts/trend_tf_sweep.py` →
`trend_sweep_report.md`, `scripts/holdout_check.py` → `holdout_report.md`,
`src/aurvex/maker_replay.py`, and the F3/F4/gross-net engine changes.
