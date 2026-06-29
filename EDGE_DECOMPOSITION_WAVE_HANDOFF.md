# AurvexAI — Edge Decomposition Wave: full handoff & next-steps report

> **Purpose of this file.** A self-contained record of everything done in the
> Edge Decomposition & Structural Execution wave, the real-data verdict, every
> artifact built, the lessons learned, and the concrete plan for the next wave.
> It is written so a fresh assistant (or engineer) can pick the project up cold
> and continue without re-deriving context. Hand this whole file to Claude chat.

---

## 0. Türkçe özet (kısa)

**Ne yaptık:** AurvexAI'nin yönlü teknik-analiz stratejilerinin (trend `bugra`,
reversion `reversion_v1`) **gerçekten para kazandırıp kazandırmadığını** veriyle
ölçtük. Bunun için önce iki ölçüm hatasını düzelttik, sonra **brüt edge'i
maliyetten ayırdık**, maker-fill ve yüksek-timeframe yapısal kaldıraçlarını
denedik, ve DSR + out-of-symbol holdout ile sağlamlık testi yaptık.

**Sonuç (NO-GO):** Hiçbir config kabul barını geçemedi. bugra 5m ölü (brüt
negatif); reversion 5m maliyet tarafından öldürülmüş (maker kurtarmadı); tek
pozitif görünen hücre (bugra 15m/4h) **tek bir sembole (BNB) sıkışmış gürültü** —
diğer sembollerde negatif, koşular arası işaret değiştiriyor.

**Sıradaki adım (öneri):** Yönlü TA terk edilip **funding/basis carry** (perp'in
kalıcı funding primi) araştırma dalgasına geçilmeli. Sizing/kaldıraç, gerçek bir
edge kabul barını geçene kadar **donuk** kalır (demir kural — bu seni korur).

---

## 1. Project context (what AurvexAI is)

AurvexAI is a clean-core crypto-futures scalp engine for Binance USDT-M perps.
Deliberately simple: one decision brain, explicit risk, paper/live parity,
observe-first shadow learning, Flask dashboard, Telegram alerts.

**Hard constraints (non-negotiable, enforced this whole wave):**
- `LIVE_ENABLED=false` always. Paper only. `LiveExecutor._send_order()` is a stub.
- No secrets in code/git.
- **Paper/live parity is sacred** — `DecisionEngine.decide()` is mode-agnostic;
  only the executor differs.
- Shadow learner never hard-vetoes; quality is label-only; governor is report-only.
- **No risk/slot/leverage increase** until a config clears the Acceptance Bar.
- DB read-only for analysis (`mode=ro`); additive-only migrations.
- Test green floor (was ≥403; now **504 passing**, nothing skipped).

Pipeline: `market data → scanner → Buğra setups [primary gate] → safety filters →
risk gate → DecisionEngine → PaperExecutor → journal/shadow/funnel → SQLite →
dashboard/telegram`. Strategy profiles in scope: `bugra_replica` (trend,
fixed-% stop), `aurvex_enhanced` (trend, ATR stop), `reversion_v1` (mean-reversion).

---

## 2. The wave's mission

Find out whether AurvexAI can produce a **structurally positive net edge** on
paper, or prove it cannot. Stop tuning signal parameters; instead (1) cleanly
separate **gross edge** from **cost**, then (2) attack the edge/cost ratio with
**structural** levers (maker-fill execution, higher timeframe), not parametric ones.

**Acceptance Bar (promote to paper only if ALL hold):** OOS net Exp-R > 0; PF > 1.1;
DSR comfortably > 0; passes out-of-symbol holdout; MaxDD < ~25–30%; ≥ 200–300 OOS
trades; edge not concentrated in one symbol/session.

**Kill Rule:** if maker-fill + higher-TF + better-instrument all fail to produce a
robust gross-positive edge, 5m directional TA is not the edge → pivot to a
structural edge (funding/basis carry) or classify as research.

---

## 3. What was done, phase by phase (with real-data findings)

### Phase 0 — read-only audit (`AUDIT_FINDINGS.md`)
Verified the assumptions the wave rests on. Key findings:
- Execution is **taker** fills; round-trip cost = (taker 0.045% + slip 0.02%)×2 =
  **0.13%**. **No maker fee existed anywhere.**
- Funding is modelled in walk-forward (forced 0.01%/8h); off in plain offline bt.
- **No lookahead** in either strategy (closed-bar only).
- **Two bugs found and fixed (see Phase 0.5).**

### Phase 0.5 — execution fixes (parity-safe, tested)
- **F3 — `close_time` bug:** `simulate_fill` stamped wall-clock `now_ms()` on
  TP/SL/BE exits, making `duration_bars`/`AvgBars` a meaningless artifact. Fixed
  to stamp the bar timestamp (legacy callers without `bar_ts` keep `now_ms()`).
  PnL-neutral. (AvgBars 744 → realistic ~115 on a synthetic check.)
- **F4 — time-stop:** added `TIME_STOP_BARS` config (default **0 = off**, parity
  preserved). Cuts a trade open ≥ N bars without TP/SL as a `"TIME"` exit. The
  reversion strategy had a hard stop but **no time-stop anywhere** — this was the
  missing piece for the reversion "clean shot".

### Phases 1–2 — gross/net decomposition
Added `realized_pnl_gross` + `funding_paid` to `Trade` (+ `r_gross`/`r_net`
properties). Invariant proven & tested: `net == gross − fees − funding`. Threaded
into walk-forward stats (`expectancy_r_gross`, `profit_factor_gross`,
`cost_drag_r`) and the decision table (`gExp-R` column).

**Real-data result (5m):**
| strategy | n | gExp-R | Exp-R (net) | verdict |
|---|---|---|---|---|
| bugra_replica | 83 | **−0.083** | −0.118 | no-alpha (dead) |
| reversion_v1 | 58 | **+0.072** | −0.016 | **cost-killed** |

Insight: reversion's cost_drag ≈ 0.088R = 0.13% cost / 1.5% fixed stop, and is
**timeframe-independent** (0.088 @5m, 0.090 @15m) — so higher TF cannot fix
reversion's cost ratio; only cheaper execution can.

### Phase 4A — conservative maker-fill experiment (`maker_replay.py`)
Limit-order model: fill only if price trades **through** the limit by a buffer
(no touch-fills — optimistic fills forbidden); maker fee on entry+TP, taker only
on SL/time-stop; tracks fill ratio + adverse selection (R of missed signals).

**Real-data result (reversion):**
| tf | taker net | maker net | fill | adverse_R | verdict |
|---|---|---|---|---|---|
| 5m | −0.133 | −0.154 | 0.91 | +0.48 | maker hurts (misses winners) |
| 15m | −0.052 | +0.0019 | 0.93 | +0.29 | barely +, concentrated (BTC/SOL + ; BNB/ETH −) |

### Phase 4B — higher-timeframe trend sweep (`trend_tf_sweep.py`)
Searched (LTF/HTF) combos, DSR-deflated across all cells. `aurvex_enhanced` (ATR
stop) blows up on higher TF (MaxDD 144–244%). `bugra 15m/4h` was the only cell
that initially flagged 5/5 (net +0.023, DSR +0.68, DD 18%, 271 trades).

### Acceptance-Bar validation of bugra 15m/4h (`holdout_check.py`) — **FAILED**
| criterion | result | pass |
|---|---|---|
| net Exp-R > 0 | −0.0002 (runs: +0.062 → +0.023 → −0.0002, sign-unstable) | ❌ |
| out-of-symbol holdout | TRAIN(BTC+ETH+SOL) **−0.027**; HOLDOUT(BNB+XRP) +0.109 | ❌ |
| not concentrated | net+ in **2/5** (BNB +0.109@80%win; BTC −0.094, SOL −0.043) | ❌ |
| DSR > 0 | −0.007 | ❌ |
| PF > 1.1 | 1.03 | ❌ |
| MaxDD < 30% | 24.4% | ✓ |
| ≥200 trades | 275 | ✓ |

By exit reason (n=275): BE 162 (+0.235), TP3 34 (+0.503), SL 48 (−1.010),
MANUAL 31 (−0.218) — the stop-outs cancel the entire winner stack. The edge lives
**entirely in BNB** and does not generalise.

### Phase 9 — final verdict (`PAPER_PERFORMANCE_REPORT.md`)
**NO-GO.** No config cleared the Acceptance Bar. Directional 5m/15m TA does not
carry a robust net-positive broad edge here. Recommend Kill-Rule pivot.

---

## 4. Artifacts delivered (all on `main`, reproducible)

| file | what it is |
|---|---|
| `AUDIT_FINDINGS.md` | Phase 0 read-only audit + the two bug fixes record |
| `PAPER_PERFORMANCE_REPORT.md` | Phase 9 consolidated NO-GO verdict |
| `EDGE_DECOMPOSITION_WAVE_HANDOFF.md` | this file |
| `src/aurvex/maker_replay.py` | conservative maker-fill replay + taker baseline |
| `scripts/decompose_edge.py` | gross/net decomposition → `trade_ledger.csv` + `decomposition_report.md` |
| `scripts/maker_experiment.py` | maker vs taker → `execution_experiments_report.md` |
| `scripts/trend_tf_sweep.py` | (LTF/HTF) sweep, DSR-deflated → `trend_sweep_report.md` |
| `scripts/holdout_check.py` | out-of-symbol holdout → `holdout_report.md` |

Engine changes (parity-safe, tested): `models.Trade` gross/net fields;
`executors.py` gross accumulation + F3 close_time + F4 time-stop; `backtest.py`
funding accumulation; `walkforward.py` gross stats + `collect_trades` sink;
`config.py` `TIME_STOP_BARS`; `Dockerfile` now copies `scripts/`.
Tests: `tests/test_execution_fixes.py`, `tests/test_maker_replay.py`.
Generated `*_report.md` / `trade_ledger.csv` are **gitignored** (a synthetic/local
run must not masquerade as real evidence — real runs happen on the engine host).

### How to reproduce on the engine host (one cmd per line, no `&&`)
```
cd ~/aurvexai
git pull origin main
docker compose up -d --build
docker compose exec engine python scripts/decompose_edge.py --tf 5m --htf 15m --limit 10000
docker compose exec engine python scripts/maker_experiment.py --tf 15m --htf 1h --limit 6000 --time-stop 16
docker compose exec engine python scripts/trend_tf_sweep.py --limit 10000
docker compose exec engine python scripts/holdout_check.py --tf 15m --htf 4h --profile bugra_replica --limit 10000
```

---

## 5. Key technical learnings (carry these forward)

1. **Always split gross from net.** It's the only way to tell a *cost-killed*
   strategy (fixable) from a *no-alpha* one (dead). This is now built in.
2. **A fixed-% stop makes cost_drag timeframe-independent** → higher TF helps
   trend (ATR/structure moves scale) but NOT fixed-% reversion.
3. **Maker fills only help when adverse selection is low.** For reversion on 5m,
   adverse selection (+0.48R) means the limit misses exactly the winners.
4. **Always validate with out-of-symbol holdout + DSR deflation.** A "5/5" cell
   (bugra 15m/4h) collapsed to noise once we checked it didn't generalise across
   symbols and deflated for the number of combos tried.
5. **Thin edges flip sign between runs.** +0.062 → +0.023 → −0.0002 across runs is
   the signature of noise, not edge.
6. **Measurement bugs masquerade as results** (the close_time/AvgBars artifact).
   Audit the measurement before trusting the numbers.

---

## 6. What's next — recommended Funding / Basis Carry research wave

Directional price prediction is not the edge. The next wave should test a
**persistent, documented** perp edge that does not depend on calling candle
direction. Same discipline (gross/net, DSR, holdout, Acceptance Bar), LIVE off,
sizing frozen.

### Why carry
Perp **funding** is paid periodically between longs and shorts; when funding is
structurally positive, a **delta-hedged short perp** (hedged vs spot or another
venue) harvests funding with minimal directional risk. **Basis** (perp vs
spot/quarterly) is a related, mean-reverting, fundable spread. These are
structural premia, not forecasts.

### Concrete plan
1. **Data pipeline (new):** fetch historical **funding rates** (Binance
   `fapi/v1/fundingRate`) and a **spot/perp basis** series per symbol; cache like
   the candle cache. (New data source — the current cache is candles only.)
2. **Carry decomposition:** measure historical funding-carry expectancy per symbol
   net of fees + the cost of maintaining the hedge; check persistence over time
   (not one lucky regime), and concentration across symbols.
3. **Hedged simulation:** simulate delta-neutral carry (short perp + long spot, or
   funding-timed perp-only) through the same Acceptance-Bar gates (DSR, holdout,
   MaxDD, ≥200–300 events).
4. **Promote only if it clears the bar**, then paper-trade it (LIVE off). Sizing
   discussion comes *after* the bar is cleared — never before.

### Open decisions for the next session
- **Direction:** (A) start the funding/basis carry wave [recommended];
  (B) keep iterating directional TA on other instruments [data says exhausted];
  (C) freeze as research.
- Whether spot data / a second venue is available for true delta-hedging, or
  whether to start funding-timed perp-only (simpler, more directional risk).
- Symbol universe for carry (funding is richest on smaller-cap perps — but mind
  liquidity).

### Environment note for whoever resumes
This Claude Code environment **cannot reach Binance** (network-blocked) and has
**no DB/cache**. All real-data measurement runs on the **engine host** via
`docker compose exec engine ...`. The assistant authors code + tests here; the
operator runs the measurement commands and pastes results back. The branch for
this work is `claude/uygula-7r2qp7`; everything is merged to `main`.

---

## 7. Status line
- Wave: **complete, NO-GO verdict delivered.**
- Tests: **504 passing**, nothing skipped. Offline `demo` green. LIVE off.
- Awaiting user decision on the Funding/Basis Carry pivot (recommended).
