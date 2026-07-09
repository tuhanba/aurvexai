# FINAL_OWNER_DECISION.md — clear answers, no hedging

**Date: 2026-07-08 (updated same day, wave 2: edge expansion).** Written
after the final scalp research wave, the edge-expansion wave and the
full-system readiness audit. Numbers and sources: `SYSTEM_STATE.md`,
`SCALP_EDGE_RESEARCH_REPORT.md`, `AURVEXAI_RESEARCH_DOSSIER.md` §12.

## 1. Is this system ready for paper?

**YES.** 661 tests green, offline demo end-to-end, Docker stack verified,
crash isolation per cycle and per symbol, heartbeat + freshness badges,
stale-data entry guard, five-gate live lock disarmed by default. Run the
`.env` in §6 and let it trade.

## 2. Is this system ready for live?

**NO — blocked, on evidence, not on infrastructure.** The infrastructure is
live-capable (Stage-3 adapter, reconcile, emergency stop). What is missing is
the paper evidence leg: **30–50 trades on the current multi-strategy epoch at
expectancy consistent with the validated numbers.** Until that exists, any
live arming would be gambling on a backtest. Also required before live:
trade-only key, canary risk (`LIVE_CANARY_RISK_PCT`), monitored first trades,
clean reconcile. This is the owner's decision to make LATER — not now.

## 3. What is the fastest VALID setup?

Three-leg multi-strategy: **donchian_trend @4h (17 coins) +
squeeze_breakout @1h (its validated 12 only) + squeeze_breakout @4h (17,
newly harness-ACCEPTED: net +0.21R, PF 1.56, DSR +3.30)** ≈ **5.5–6
trades/day fleet-wide**. That is the measured frequency ceiling with
positive edge. Optional validated bump: `DON_ENTRY_BARS=10` (+14% donchian
trades at ~94% of yield).

**Scalp is not and will not be the fast option.** Four campaigns, ~17
families, 60+ cells, all net-negative after cost — including this session's
final 12 cells (leader-lag, order-flow proxies, break-retest, inside-bar,
prior-day reclaim: 0 of 12 coins positive in ANY cell). The verdict is
structural: taker cost (0.13–0.14%) is 0.2–0.6R at scalp stops; the best
gross OHLCV edge at those horizons is +0.08R. Anyone selling you a "scalp
mode" on this data is selling losses.

## 4. What is the SAFEST valid setup?

Same strategies, lower sizing: `RISK_PCT=1.0`, `MAX_OPEN_TRADES=4`,
`MAX_PORTFOLIO_EXPOSURE_PCT=200`. Same edge per trade, roughly half the
equity swings of the 2% config. The kill switch (−10%/day) and profit lock
(+10%/day) stay on in every variant.

## 5. What should be DISABLED (and stay disabled)?

- All retired scalp profiles (`aurvex_enhanced`, `bugra_replica`,
  `reversion_v1`) — never redeploy them as the trading profile.
- `SCORE_AS_GATE=false` (score measured anti-predictive as a gate).
- `RISK_MODULATION_ENABLED=false`, `SHADOW_APPLY=false` until shadow buckets
  reach sample size AND monotonicity (they are observe-only support layers).
- `LIVE_ENABLED` / `LIVE_SEND_ORDERS` — false until §2 passes.
- Auto-scanned exotic universe — keep `UNIVERSE_INCLUDE` pinned to the 17.

## 6. The exact `.env` to run now (balanced paper)

```
AX_MODE=paper
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
LIVE_ENABLED=false
LIVE_SEND_ORDERS=false
DASHBOARD_AUTH_USER=<pick-a-user>
DASHBOARD_AUTH_PASS=<pick-a-strong-pass>
TELEGRAM_BOT_TOKEN=<your token>
TELEGRAM_CHAT_ID=<your chat id>
```

Why RISK_PCT=1.5 and 6 slots: donchian's wide stops saturate the exposure
cap at 2–3% risk after ~2 positions (measured — the all-long loss cluster);
1.5% fits 3–5 concurrent positions with the same per-trade edge and lower
variance. Safer: drop to 1.0. Never above 3.

## 7. The Docker commands to run (one per line)

```
git pull
```
```
cp .env.example .env        # first time only, then edit per §6
```
```
docker compose down
```
```
docker volume rm aurvexai_aurvex-data   # OPTIONAL fresh epoch — destroys paper history
```
```
docker compose up -d --build
```
```
docker compose ps
```
```
curl -fsS http://localhost:5000/health
```
```
bash scripts/logs.sh engine
```

Full operations (backup/restore/reset/Telegram): `SERVER_RUNBOOK.md`.

## 8. Live: blocked or allowed?

**BLOCKED.** By design and by evidence. The unlock path is written in
`LIVE_READY_CHECKLIST.md` and §2 above; it starts with the next 30–50 paper
trades and ends with a canary, not a switch-flip.

## 9. What to monitor for the next 30–50 trades

Per strategy (dashboard + `/summary` in Telegram; the 4h squeeze leg
reports separately as `squeeze_breakout@4h`):
1. **Expectancy (net R/trade)** — donchian toward +0.2…+0.3R, squeeze@1h
   toward +0.05…+0.1R, squeeze@4h toward +0.15…+0.2R. Alarm: any leg
   persistently below −0.1R after ≥20 trades of that leg. Special watch:
   donchian's 2025+ half measured soft in the replication sim — if donchian
   paper expectancy sits near zero after 30 trades while squeeze@4h
   performs, that soft-regime flag is confirmed and sizing should shift
   (owner decision, not automatic).
2. **Stop quality** — losses should cluster at ≈−1.0R. Worse-than-−1.2R
   losses mean slippage/liquidation-buffer problems, not signal problems.
3. **Diversification** — 3–5 concurrent positions, not 2; exposure-cap
   rejects should be a minority of rejects. If `exposure_cap` dominates,
   lower RISK_PCT further.
4. **Universe discipline** — every trade in the 17-coin list; any exotic
   symbol appearing = config regression.
5. **Data health** — DATA badge fresh; `stale_data` rejects near zero in the
   funnel; no repeated snapshot failures for one symbol.
6. **Kill switch / profit lock** — fire correctly at ±10%; both events show
   in Telegram.
7. **No parameter reactions** — do NOT tune anything to these 30–50 trades.
   That is the overfitting trap the whole methodology exists to prevent.

When those 30–50 trades exist, come back with the numbers and make the live
decision against §2 — not before.


## 10. AGGRESSIVE MODE (owner-requested, 2026-07-09) — the measured middle

The demand was 3–5%/day minimum. The honest math: +3%/day average needs
~2 R/day of net edge; the entire measured portfolio produces 0.2–0.3 R/day.
Bridging that gap with size means ~10–15% risk/trade, where one ordinary
5-loss streak is −40…−75% — the kill switch would (correctly) halt the
account long before. No measured configuration averages 3–5%/day; anything
claiming to is sizing into ruin. INDIVIDUAL +3…6% days will happen at 3%
risk (one 2R runner = +6%); the average cannot.

**The measured middle — maximum aggression the edge survives:**

```
RISK_PROFILE=aggressive_plus
STRATEGIES=donchian_trend@4h/1d:n=10 squeeze_breakout@1h/4h:ts=24:u=BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TON+TRX+DOT squeeze_breakout@4h/1d:ts=24:q=30 ichimoku_trend@4h/1d
SHADOW_ONLY_SETUPS=ichimoku_trend
```

(risk 3% — the max-eff study's winning multiplier; 6 slots; profit lock 20%
so runner days are not capped; kill switch UNCHANGED at 10% — it is the
ruin guard, never a tunable; + the validated more-action package n=10/q=30
for ~+25–30% trade frequency at ~85–93% per-trade yield.)

Honest expectation at validated numbers: **~0.75–1%/day compounding
(~25–35%/month)** with 30–40% drawdowns and losing WEEKS. That is the
ceiling this edge supports. The next multipliers after the evidence window:
evidence-gated sizing (RISK_MODULATION staircase), the ichimoku swap if it
beats donchian live, and CAPITAL — the percentage machine scales linearly.

Rule of engagement: run aggressive_plus in PAPER for the 30–50-trade
window like everything else. If the numbers hold, it is the live-candidate
config; if they don't, drop back to §6. Never both loosen risk AND skip
the evidence window.
