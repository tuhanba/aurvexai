# Carry Phase 0 — Review & Verdict (gross funding-harvest gate)

**Status: GO to hedge-simulation phase — with a refined universe and a
tail-centric mandate.** This is NOT a promote-to-paper bar.

This file is the human review the Phase-0 gate requires before any later phase
begins. It interprets a real engine-host run (Binance USDT-M, full realized
funding history per symbol). The raw, regenerable findings live in the
gitignored `CARRY_PHASE0_FINDINGS.md` (produced on the engine host from real
data); this review is the durable record of the decision and its caveats.

Run reviewed: full history per symbol (BTC 7453 settlements from 2019-09 →
2026-06; alts 6.3k–7.1k from their listing), 8h cadence inferred for all,
spot leg reachable for all 8 symbols.

> Reproduce the underlying numbers (engine host, `--refresh` mandatory to
> overwrite any earlier truncated cache):
> `docker compose exec engine python scripts/carry_data.py --universe BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK --refresh`
> `docker compose exec engine python scripts/carry_phase0.py --universe BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK`

---

## 1. Gate evaluation (Section-4)

All four gross-stage criteria hold, so the gate is **GO**. But the criteria are
deliberately gross-stage and lenient; the honest reading below matters more than
the binary.

| Criterion | Result |
| --- | --- |
| Gross positive & clears first-order cost on >1 symbol | PASS (6 symbols, high t-stat) |
| Positive across multiple regimes | PASS (BTC/LINK every quarter; see §2) |
| Broadly positive across the universe (not 1–2 symbols) | PASS (top contributor XRP only ~20% of summed positive gross) |
| Block-bootstrap / Newey-West significance comfortably positive | PASS (6 symbols, NW t 4.8–15.6, bootstrap CI lower bound > 0) |

Gross annualized **on notional** (frictionless; NOT a capital yield):
BTC +11.7%, ETH +14.1%, XRP +15.0%, LINK +14.0%, DOGE +12.6%, AVAX +7.0%,
SOL +0.07% (t=0.02), BNB −0.24% (t=−0.17).

## 2. Regime durability — who is real, who is dead

- **BTC, LINK** — every quarter 2019/2020→2026 positive, including the 2022
  bear. Most robust.
- **DOGE, ETH** — one negligible/event negative quarter each (DOGE 2026Q1;
  ETH 2022Q3, the Merge). Robust.
- **XRP** — strong, but flips negative in 2022Q3–Q4 and again 2026Q1–Q2.
- **AVAX** — the weakest "alive" symbol: funding flips sign repeatedly
  (2022Q2–Q4, 2024Q3, 2025Q2/Q4, 2026Q1). Regime-fragile; +7% is real but thin.
- **SOL — DEAD.** Net ~0 (t=0.02); 2022Q4 mean −0.00109 at 33% positive.
- **BNB — DEAD / structurally negative.** Most quarters negative, often
  0–30% positive. A short-perp harvester *loses* on BNB. (The opposite
  trade — long-perp collecting negative funding — is a *separate* hypothesis,
  out of scope here.)

**Action: the sim universe is the 6 — BTC, ETH, XRP, LINK, DOGE, AVAX.** Drop
SOL and BNB from the harvest set (keep as negative controls if useful).

## 3. The real risk is the negative-funding tail, and it is event-driven

A static short harvester *pays* during negative-funding regimes, and the worst
episodes line up exactly with sharp up-moves / short squeezes — i.e. the moments
the short leg is *also* closest to liquidation. This, not delta drift, is the
realistic killer the sim must model.

- **SOL 2022-11-08: depth −0.285 (28.5% of notional) over 51 settlements**
  (FTX/Alameda collapse). On its own this destroys a static SOL harvester — and
  is why SOL nets to zero.
- **ETH 2022-09-08: −0.0135** (the Merge — PoW-fork-dividend shorting).
- **BTC 2020-03-12: −0.0104** (COVID crash). LINK same window −0.016.
- DOGE −0.015 (2021-01 WSB/Elon squeeze), XRP −0.015 (2020-12 SEC suit),
  AVAX −0.027.

Even the survivors carry ~1–1.4% single-episode bleeds on notional; SOL/BNB are
an order of magnitude worse.

## 4. Funding is compressing — historical yield ≠ today's run-rate

Across almost every symbol, **2026Q1/Q2 are the lowest funding of the entire
sample** (BTC 2026Q2 +0.0000086 vs a historical mean ~0.0001; ETH ~0;
XRP/AVAX/SOL/DOGE negative in 2026Q1). The headline 11–15% gross is weighted to
the 2020–2021 bull. Today's run-rate is a fraction of it. The sim must weight the
recent regime, not the full-sample average.

## 5. Significance — solid, one methodological note

Six symbols are bootstrap-positive with NW t-stats 4.8–15.6; SOL/BNB are
correctly excluded (CI straddles zero). **Note:** on the original run the
autocorrelation horizon for BTC/ETH/XRP/LINK saturated the 50-lag cap — funding
stays correlated past ~16 days — so a 50-block bootstrap slightly *understates*
the variance of the mean. The cap has been raised to 200 (~66 days) in
`scripts/carry_phase0.py`; re-run to refresh the significance block lengths.
This does not change the verdict (t-stats of 12–16 survive a doubled SE), it
just makes the CI honest.

## 6. Framing that must not be lost downstream

**Every yield here is gross, frictionless, and on NOTIONAL.** It excludes hedge
capital, the 4 legs of fees, the collateral buffer (which earns ~0), and the
tail losses in §3. Do not let "+14% on notional" read as "+14% on capital." The
whole point of the sim phase is to find out what, if anything, survives those.

## 7. Open decisions this run informs (still deferred to the sim pack)

- **Hedge availability — RESOLVED for the spot route:** spot was reachable for
  all 8 symbols, so a spot-leg hedge is feasible. Spot-vs-quarterly remains a
  sim-phase choice.
- **Sim universe:** the 6 (§2), with hard liquidity/spread thresholds.
- **Capital / collateral model:** anchor the liquidation stress tests to the §3
  dates (FTX-SOL 2022-11, Merge-ETH 2022-09, COVID-BTC 2020-03). The short-leg
  MMR breach under a sharp up-move is the central question.
- **Maker fill model:** entry/exit maker, taker only on forced unwind.
- **Architecture:** the paper sim must faithfully model both legs (spot + perp
  + funding settlement + collateral) so eventual live parity holds.

---

_Reviews `CARRY_PHASE0_FINDINGS.md` (gitignored, engine-host generated).
Generators: `scripts/carry_data.py`, `scripts/carry_phase0.py`._
