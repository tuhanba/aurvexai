# SYSTEM_STATE.md — the single source of truth

**Updated: 2026-07-09 (campaign 5: htf_liquidity_sweep_bos_fvg — NO-GO).**
If any
other document contradicts this file, this file wins. (README/ROADMAP/
LIVE_READY_CHECKLIST were written at different stages of the project; they
are aligned to this file as of this date.)

---

## 1. What the system is now

AurvexAI is a **multi-strategy crypto-futures engine** on Binance USDT-M
perpetuals — no longer "a scalp engine". Scalp was the original goal; it was
researched to exhaustion on real data and **failed everywhere after cost**
(see §3). The system now runs the validated **swing/positional** edges:

- One decision brain shared by paper / live / backtest (parity is sacred).
- Multi-strategy mode (`STRATEGIES` env): several validated edges on ONE
  shared account — one balance, one kill switch, one profit lock, one slot
  pool, one-position-per-symbol across strategies.
- Explicit risk: % risk per trade, 10% daily-loss kill switch, 10% daily
  profit lock, exposure cap, cooldowns, stale-data entry guard.
- Paper by default. A real order adapter exists (`live_orders.py`) but is
  disarmed behind a five-gate lock; every default keeps it disarmed.

## 2. Validated edges (evidence-gate PASSED)

All measured on real Binance USDT-M history (`data.binance.vision`),
walk-forward OOS through the engine's own harness, DSR-deflated for every
cell tried, out-of-symbol holdout, kill-rule discipline.

| edge | TF | net Exp-R | PF | MaxDD@2% | DSR | verdict |
|---|---|---|---|---|---|---|
| **donchian_trend** (20-bar channel breakout, 2×ATR stop, channel exit) | 4h | **+0.284** | 1.37 | 19.3% | +2.44 | **ACCEPTED 5/5** — primary |
| **squeeze_breakout** (vol-squeeze + range break, 24h time-stop, SMA200 filter) | 1h | **+0.088** | 1.12 | 32% (≈24% @1.5%) | +1.58 | **ACCEPTED** — secondary. **Universe: its validated 12 coins ONLY** (measured negative on the 5 donchian-expansion coins — use `u=` in STRATEGIES) |
| **squeeze_breakout @4h** (same rules, 24-bar=96h time-stop) — NEW 2026-07-08 | 4h | **+0.193** (majors) / **+0.211** (17 coins) | 1.49 / 1.56 | 15.5% / 9.5% @1.5% | **+2.63 / +3.30** (deflated n_trials=95) | **ACCEPTED — real harness, both split halves positive (H1 +0.21 / H2 +0.18), 15/17 coins** |
| **ichimoku_trend** (TK-cross + cloud-side confirm, TKCROSS exit) — NEW 2026-07-09 | 4h | **+0.314** | **1.71** | 14.7% @1.5% | **+4.14** (n_trials=121) | **ACCEPTED — strongest harness result in the book.** Deployed **SHADOW-ONLY** (additive-edge bar unproven vs don+sqz; positioned as donchian's regime-substitute candidate) |
| **carry** (spot-long + perp-short funding harvest, cross-margin) | 8h settle | +4…8%/yr on capital, t>11, maxDD <3% | — | — | — | validated in research; **NOT built into the engine yet** |

Character warning: both directional edges are **swing/positional** (hours to
days). Neither can be sped up — donchian dies below 4h, squeeze below 1h;
every faster cell measured net-negative.

## 3. Failed edges (evidence-gate NO-GO — do not retry without new data)

Roughly **18 families / 75+ cells** of short-timeframe scalping have been
tested across five campaigns (2026-06-29, 2026-07-05 ×2, 2026-07-08,
2026-07-09). Every cell net-negative after realistic taker+slippage cost.
The graveyard:

- Buğra 5-condition directional TA — 20/20 cells net-negative (5m→4h).
- Mean-reversion (Bollinger stretch), RSI2/Connors, VWAP reversion.
- Liquidity-sweep / stop-hunt reversal (ICT/SMC), opening-range breakout,
  momentum continuation (5m/15m).
- Cross-sectional momentum (daily), funding-extreme directional (regime
  mirage caught by holdout), pullback-in-trend.
- **2026-07-08 wave**: cross-symbol leader-lag (BTC impulse →
  alt follow AND fade, 5m/15m), rejection-wick reversal, high-volume failed
  breakout, volume+range impulse continuation, break-and-retest, inside-bar
  breakout, prior-day sweep-reclaim — **12/12 cells NO-GO**, both halves
  negative, **0 of 12 coins positive in any cell**
  (`SCALP_EDGE_RESEARCH_REPORT.md`).
- **2026-07-09 campaign 5 (owner-requested)**: htf_liquidity_sweep_bos_fvg —
  the full ICT/SMC multi-TF model (HTF liquidity map sweep → 5m BOS/IFVG
  confirm → 1m BOS trigger → liquidity-draw TP), 1m execution data, 14
  pre-registered cells over confirmation/trigger/entry/stop/TP/session/trend
  axes — **14/14 NO-GO, 11/14 gross-negative before cost, 0/12 coins
  positive, all acceptance criteria failed**
  (`HTF_LIQUIDITY_SWEEP_RESEARCH_REPORT.md`). Trial count now 161.

**Structural reason:** gross edge on OHLCV signals at scalp horizons is at
best +0.03…+0.08R; taker round-trip cost (~0.13–0.14%) is 0.2–0.6R at
scalp-sized stops. Cost always wins. Maker execution was tested — adverse
selection makes it worse. A real scalp would need L2/tick data + low-latency
infra, which this system does not have. **Scalp is closed.**

## 4. What is paper-only vs live-ready-infrastructure-only

- **Paper-only (running):** multi-strategy donchian 4h + squeeze 1h on one
  shared 200 USDT paper account.
- **Live-ready infrastructure only:** `live_orders.py` (Stage-3 adapter:
  entry+SL/TP, partial fills, timeout/retry, reconcile, emergency stop).
  Exists, tested, **disarmed** behind the five-gate lock:
  `LIVE_ENABLED=true` + `LIVE_HUMAN_CONFIRM` token + Telegram
  `/livemode confirm <token>` + restart + `LIVE_SEND_ORDERS=true` + API keys.
- **Not built:** carry executor (research-validated, engine port pending —
  the only meaningful "new strategy" work left).

## 5. What is still NOT allowed for real money

Everything. Live promotion requires ALL of:
1. 30–50 paper trades on the current multi-strategy epoch with expectancy
   consistent with the validated numbers (not tuned to those trades),
2. owner's explicit decision,
3. trade-only (no-withdraw) Binance key,
4. canary sizing (`LIVE_CANARY_RISK_PCT`) with monitored first trades and a
   clean `reconcile()`,
5. the five-gate lock opened deliberately, gate by gate.

## 6. Recommended `.env` for paper (current)

```
RISK_PROFILE=aggressive_paper
INITIAL_PAPER_BALANCE=200
STRATEGIES=donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24:u=BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TON+TRX+DOT squeeze_breakout@4h/1d:ts=24 ichimoku_trend@4h/1d
SHADOW_ONLY_SETUPS=ichimoku_trend
GLOBAL_RANKING=true
RANK_KEY=edge
LTF_LIMIT=525
RISK_PCT=1.5
MAX_OPEN_TRADES=6
MAX_PORTFOLIO_EXPOSURE_PCT=200
MAX_LEVERAGE=10
UNIVERSE_SIZE=17
UNIVERSE_INCLUDE=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,ATOM/USDT:USDT
STALE_ENTRY_GUARD_BARS=3
KLINE_CACHE_ENABLED=true
UNIVERSE_REFRESH_SEC=600
AX_MODE=paper
LIVE_ENABLED=false
LIVE_SEND_ORDERS=false
```

Three legs on ONE account (2026-07-08 wave): donchian 4h on all 17;
squeeze 1h pinned to its validated 12 via `u=` (it measured NEGATIVE on the
5 donchian-expansion coins — the per-strategy universe restriction exists
exactly for this); squeeze 4h on all 17 (newly harness-ACCEPTED). Same
profile at two TFs is supported: the 4h instance's signals/trades carry
setup_type `squeeze_breakout@4h` so its stats stay separate. One position
per symbol across all legs; note donchian@4h and squeeze@4h are both 4h
breakout-style, so expect correlation between them — the shared kill switch
and exposure cap are the containment.

Why 1.5% and not 2–3%: donchian's wide 2×ATR stops make each position large
in notional; at RISK_PCT≥2 the 200% exposure cap saturates after ~2 positions
and diversification collapses (measured live — the all-long loss cluster).
1.5% fits 3–5 concurrent positions: same per-trade R-edge, smaller swings.
Safer variant: `RISK_PCT=1.0`. Do NOT raise above 3 (band ceiling).

Why 17 coins: the edge is coin-specific. The expansion study validated
exactly these 17 (meanR +0.334, t +4.74, n=3,422). Beyond them, added coins
measured flat-to-negative — more universe = less edge.

## 7. Fastest validated setup today

Three-leg multi-strategy (§6): donchian@4h (~1.4–2/day) + squeeze@1h
(~3/day on its 12) + squeeze@4h (~1/day on the 17) ≈ **5.5–6 trades/day
fleet-wide** — the measured frequency ceiling at optimal yield.

**Validated "more action" package (owner-selectable, per-leg spec options;
each costs some per-trade edge — dossier §13):**
- `squeeze_breakout@4h/1d:ts=24:q=30` → +27% trades on that leg at ~85% of
  its yield (harness ACCEPTED: net +0.161R, PF 1.43, DSR +2.82).
- `donchian_trend@4h/1d:n=10` → +12% trades at ~93% of yield (phase-5 +
  wave-3 validated).
Anything faster than this requires an edge that does not exist in this
data (§3). Beyond this, the honest path is the carry engine (uncorrelated,
slow), not faster direction-calling.

## 8. What is still being researched

- **Scalp: nothing.** The families are exhausted; the verdict is structural
  (cost > gross edge), not parameter-sensitive. Reopen only with L2/tick data
  or materially lower fees.
- **Closed this wave (2026-07-08), do not retry without new data:**
  donchian on 12 NEW coins (H1 +0.63R → H2 −0.02R, killed — the edge stays
  coin-specific); squeeze@1h on expansion/new coins (killed); donchian@1d
  (H2 ≈ 0, killed); BTC-SMA200 regime hard-filter on donchian (no H2
  improvement, halves trades — regime stays advisory-only). Squeeze@2h on
  the 17 is a **WATCH** (+0.068R, both halves positive but t<2 per half;
  not deployed — three squeeze TFs would stack correlation for little
  yield).
- **Watch flag:** in the replication sim, donchian@4h's recent half (2025+)
  is soft (+0.03R vs +0.48R in 2023–24). The authoritative 5.8-year harness
  validation stands, but this is exactly what the 30–50-trade paper window
  must confirm. Squeeze@4h is strong in BOTH halves including 2025+.
- **Carry executor**: engine port of the validated funding-harvest strategy
  (cross-margin, universe 5) as a separate low-frequency engine with its own
  risk rules. This is engineering, not research.
- **Paper evidence accumulation**: 30–50 trades per strategy on the current
  epoch before any judgement; no parameter reacts to a handful of live trades.

## 9. Support layers (advisory, never hard vetoes)

Hard gates are ONLY: data invalid/stale, spread/slippage guards, daily loss
kill switch, daily profit lock, max open/exposure caps, same-symbol/cooldown,
live five-gate lock, strategy invalidation (its own stop/exit).
Score/shadow/quality/governor are advisory: `SCORE_AS_GATE=false`,
`RISK_MODULATION_ENABLED=false`, `SHADOW_APPLY=false`, governor
`report_only` — all measured-before-promoted, all reversible.

## 10. Data flow & speed (2026-07-08 wave)

- **Closed-bar-aware kline cache** (`KLINE_CACHE_ENABLED=true`): klines are
  refetched only when a new bar can have closed. At the deployed
  17×(1h+4h+1d) configuration this cuts per-cycle REST calls from ~69 to
  ~17–18 (order book stays live every snapshot; 1h refreshes once/hour,
  4h/1d once per bar). Parity-safe: decisions read closed bars, which are
  byte-identical between refreshes. Failed refetch serves the last good
  cache; the stale-entry guard blocks entries if it ever ages out.
- **Universe re-rank interval** (`UNIVERSE_REFRESH_SEC=600`): the heavy
  `fetch_tickers` runs every 10 min instead of every 20 s cycle; the pinned
  17-coin deployment barely uses the ranking anyway.
- **Stale-entry guard** (`STALE_ENTRY_GUARD_BARS=3`) blocks NEW entries on
  stale data engine-side; funnel reason `stale_data`.

## 11. Shadow / Friday policy

Friday/CEO layer stays excluded (CLAUDE.md non-negotiable #5) — its useful
10% already exists as the read-only governor report (`python main.py report
[--telegram]`) with the CEO_SUMMARY verdict panel. What shadow does: tracks
every signal (taken AND rejected) per strategy, resolves outcomes, measures
score-bucket predictivity. It never vetoes. The governor report now includes
**SHADOW_READINESS**: per-strategy resolved counts against the explicit
activation staircase — stage 1 `SHADOW_APPLY` at ≥50 resolved/setup (soft
score nudges), stage 2 `RISK_MODULATION_ENABLED` only when buckets are
sufficient (N≥100) AND monotone-positive. Owner flips the flags when the
report says ELIGIBLE; both reversible, neither ever blocks a trade.

## 12. Test floor

684 passing (`pytest`), including: no-lookahead, one-fill-per-closed-candle,
paper/live parity, multi-strategy allocation, same-profile-two-TF routing,
per-strategy universe filter, exposure caps, live-gate disarmed-by-default,
stale-entry guard, kline cache, shadow readiness.
