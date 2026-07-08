# SYSTEM_STATE.md — the single source of truth

**Updated: 2026-07-08.** If any other document contradicts this file, this
file wins. (README/ROADMAP/LIVE_READY_CHECKLIST were written at different
stages of the project; they are aligned to this file as of this date.)

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
| **squeeze_breakout** (vol-squeeze + range break, 24h time-stop, SMA200 filter) | 1h | **+0.088** | 1.12 | 32% (≈24% @1.5%) | +1.58 | **ACCEPTED** — secondary |
| **carry** (spot-long + perp-short funding harvest, cross-margin) | 8h settle | +4…8%/yr on capital, t>11, maxDD <3% | — | — | — | validated in research; **NOT built into the engine yet** |

Character warning: both directional edges are **swing/positional** (hours to
days). Neither can be sped up — donchian dies below 4h, squeeze below 1h;
every faster cell measured net-negative.

## 3. Failed edges (evidence-gate NO-GO — do not retry without new data)

Roughly **17 families / 60+ cells** of short-timeframe scalping have been
tested across four campaigns (2026-06-29, 2026-07-05 ×2, 2026-07-08). Every
cell net-negative after realistic taker+slippage cost. The graveyard:

- Buğra 5-condition directional TA — 20/20 cells net-negative (5m→4h).
- Mean-reversion (Bollinger stretch), RSI2/Connors, VWAP reversion.
- Liquidity-sweep / stop-hunt reversal (ICT/SMC), opening-range breakout,
  momentum continuation (5m/15m).
- Cross-sectional momentum (daily), funding-extreme directional (regime
  mirage caught by holdout), pullback-in-trend.
- **2026-07-08 wave (this session)**: cross-symbol leader-lag (BTC impulse →
  alt follow AND fade, 5m/15m), rejection-wick reversal, high-volume failed
  breakout, volume+range impulse continuation, break-and-retest, inside-bar
  breakout, prior-day sweep-reclaim — **12/12 cells NO-GO**, both halves
  negative, **0 of 12 coins positive in any cell**
  (`SCALP_EDGE_RESEARCH_REPORT.md`).

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
STRATEGIES=donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24
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
AX_MODE=paper
LIVE_ENABLED=false
LIVE_SEND_ORDERS=false
```

Why 1.5% and not 2–3%: donchian's wide 2×ATR stops make each position large
in notional; at RISK_PCT≥2 the 200% exposure cap saturates after ~2 positions
and diversification collapses (measured live — the all-long loss cluster).
1.5% fits 3–5 concurrent positions: same per-trade R-edge, smaller swings.
Safer variant: `RISK_PCT=1.0`. Do NOT raise above 3 (band ceiling).

Why 17 coins: the edge is coin-specific. The expansion study validated
exactly these 17 (meanR +0.334, t +4.74, n=3,422). Beyond them, added coins
measured flat-to-negative — more universe = less edge.

## 7. Fastest validated setup today

Multi-strategy donchian(4h) + squeeze(1h) on the 17-coin universe:
**≈4.5–5 trades/day fleet-wide** (donchian ~1.4–2/day + squeeze ~3/day).
This is the measured frequency ceiling with positive edge. Optional
still-validated frequency bump: `DON_ENTRY_BARS=10` (+14% trades, ~94% of
yield). Anything faster requires an edge that does not exist in this data
(§3). If more activity is wanted beyond this, the honest path is the carry
engine (uncorrelated, slow), not faster direction-calling.

## 8. What is still being researched

- **Scalp: nothing.** The families are exhausted; the verdict is structural
  (cost > gross edge), not parameter-sensitive. Reopen only with L2/tick data
  or materially lower fees.
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

## 10. Test floor

661 passing (`pytest`), including: no-lookahead, one-fill-per-closed-candle,
paper/live parity, multi-strategy allocation, exposure caps, live-gate
disarmed-by-default, stale-entry guard.
