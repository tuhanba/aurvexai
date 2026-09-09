# FTMO challenge-mode risk (pass faster, bounded downside)

The bottleneck for reaching a funded account quickly is **time-to-pass**, not
monthly yield. A failed *challenge* costs only the entry fee (~€139), not real
capital — so the risk that is optimal during the challenge is higher than the
risk that is optimal once funded (where a loss is real money).

## Monte-Carlo (4-edge portfolio R-distribution, $25k 2-Step, Phase 1 +10%)

4000 resampled account paths, ~3 trades/day, FTMO rule math, no time limit.

| risk % | pass rate | daily breach | max breach | avg days-to-pass | p95 maxDD |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 100% | 0% | 0% | ~25 | 8.3% |
| 0.75 | 97% | 0% | 3% | ~17 | 10.9% |
| 1.00 | 92% | 0% | 8% | ~12 | 12.6% |
| 1.25 | 87% | 0% | 13% | ~9 | 13.5% |
| 1.50 | 80% | 1% | 19% | ~8 | 14.3% |
| 2.00 | 31% | 67% | 2% | ~4 | 9.3% |

## Protocol

- **Challenge mode (Phase 1 & 2): risk 0.75–1.0%.** Roughly halves time-to-pass
  (~25 → ~12–17 days for Phase 1) at 92–97% pass. The ~3–8% failures cost only the
  fee, so the expected extra fee (~€10) is a trivial price for the speed.
- **Funded mode: risk 0.50%.** Real capital → the validated safe ceiling (per-fold
  maxDD ≤ 8.6%, no breach). Never run funded above 0.5%.
- **≥2.0% is a cliff** — daily-breach rate explodes (67%). Do not exceed ~1.0–1.25%.

Implementation is one EA input: `RiskPct=1.0` during the challenge, `RiskPct=0.5`
once funded.

## Honest caveats

The R-distribution here is the raw backtest (mean +0.27R) — **optimistic**, because
real fills (spread + slippage) will lower it. So real pass rates will be lower and
days-to-pass longer; the **relative** risk/speed trade-off is the robust takeaway,
not the absolute pass %. The demo GO (KAPI 1) is what pins the real R — only then
should real challenge money be spent. Reproduce with `ftmo_sim.monte_carlo` on the
4-edge portfolio R-samples.
