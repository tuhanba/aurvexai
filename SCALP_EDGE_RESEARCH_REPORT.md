# SCALP_EDGE_RESEARCH_REPORT.md — the complete scalp verdict

**Updated: 2026-07-08.** Consolidates every scalp/faster-edge family ever
tested on this system, including the final 2026-07-08 wave that closed the
remaining untested families. **Definitive verdict: NO-GO — there is no
taker-executable, OHLCV-signal scalp edge on Binance USDT-M perps with this
system's execution and data.**

## Protocol (identical across all campaigns)

- Real Binance USDT-M history from the official `data.binance.vision`
  archive (fapi is geo-blocked from the research runners; the archive is not).
- Signals computed on CLOSED bars only; entry at next bar open (no lookahead,
  no same-bar fills, no entry-bar TP/SL fantasy).
- Conservative fills: stop-first when a bar touches both stop and target.
- Costs: taker 0.045% + slippage 0.02% per side ≈ 0.13–0.14% round trip,
  charged in R against the actual stop distance; funding charged where holds
  cross settlements.
- Walk-forward OOS or split-half (H1 discovery → H2 confirm); out-of-symbol
  holdout on the multi-coin sets; DSR multiple-testing deflation across every
  cell tried in a campaign; kill-rule — a holdout sign flip kills the cell,
  no re-tuning to rescue it.

## Campaign 4 (2026-07-08, this session): the last untested families

Data: 24 months (2024-07 → 2026-06) of 5m and 15m klines, 12 validated coins
(BTC ETH SOL BNB XRP DOGE ADA AVAX LINK TON TRX DOT), 70,080 15m + 210,240 5m
bars per coin, gapless, timestamp-defect-normalized. 12 pre-registered cells.

| cell | n | gross R | net R | PF | H1 R (t) | H2 R (t) | coins+ | verdict |
|---|---|---|---|---|---|---|---|---|
| F1 leader-lag follow @5m (BTC impulse z>2.5 → alts) | 46,609 | +0.060 | −0.264 | 0.65 | −0.250 (−25.2) | −0.279 (−25.0) | 0/11 | **NO-GO** |
| F1 leader-lag fade @5m | 46,607 | −0.016 | −0.340 | 0.56 | −0.310 (−33.3) | −0.370 (−40.9) | 0/11 | **NO-GO** |
| F1 leader-lag follow @15m | 15,857 | +0.079 | −0.091 | 0.86 | −0.060 (−3.6) | −0.122 (−7.0) | 0/11 | **NO-GO** |
| F1 leader-lag fade @15m | 15,857 | −0.053 | −0.223 | 0.67 | −0.216 (−14.3) | −0.230 (−15.3) | 0/11 | **NO-GO** |
| F2a rejection-wick reversal @15m ×12 | 7,341 | +0.005 | −0.196 | 0.68 | −0.197 (−8.5) | −0.196 (−9.3) | 0/12 | **NO-GO** |
| F2a rejection-wick @5m majors | 8,317 | −0.019 | −0.459 | 0.42 | −0.430 (−22.2) | −0.488 (−24.5) | 0/5 | **NO-GO** |
| F2b high-vol failed breakout @15m ×12 | 24,076 | −0.022 | −0.359 | 0.58 | −0.331 (−19.3) | −0.387 (−23.6) | 0/12 | **NO-GO** |
| F2b failed breakout @5m majors | 29,589 | +0.007 | −0.659 | 0.40 | −0.616 (−38.5) | −0.702 (−49.7) | 0/5 | **NO-GO** |
| F2c volume+range impulse continuation @15m ×12 | 10,482 | +0.056 | −0.240 | 0.71 | −0.266 (−11.3) | −0.214 (−7.6) | 0/12 | **NO-GO** |
| F3 break-and-retest @15m ×12 | 20,482 | +0.036 | −0.266 | 0.70 | −0.257 (−13.7) | −0.275 (−13.1) | 0/12 | **NO-GO** |
| F4 inside-bar breakout @15m ×12 | 21,443 | −0.013 | −0.878 | 0.45 | −0.832 (−26.7) | −0.924 (−27.1) | 0/12 | **NO-GO** |
| F5 prior-day sweep-reclaim @15m ×12 | 16,335 | −0.014 | −0.322 | 0.64 | −0.326 (−15.9) | −0.318 (−14.9) | 0/12 | **NO-GO** |

Reading: not one cell is even close. The best gross signals (+0.06…+0.08R:
leader-lag follow, impulse continuation, break-retest) are real but tiny;
cost at scalp-sized stops is 0.2–0.6R and erases them several times over.
Half the families have no gross alpha at all. **Zero of 12 coins positive in
any cell.** Both halves agree everywhere — this is not noise, it is the
market's cost/edge structure. Campaign-wide trial count is now 88
(76 prior + 12 here): even a marginally positive cell would not have
survived deflation.

Reproducible: `scalp_families.py` harness (session artifact; rules
pre-registered in its docstring), archive fetcher normalizes the 2025+
microsecond-timestamp defect.

## Campaigns 1–3 (2026-06-29 → 2026-07-05): the prior graveyard

| family | TF | verdict | why |
|---|---|---|---|
| Buğra 5-cond directional TA (20 cells) | 5m→4h × 15m→1d | NO-GO | gross +0.01…+0.03R never clears 0.03–0.09R cost; 20/20 net-negative over 3y |
| Mean-reversion v1 (Bollinger stretch) | 1m/5m/15m | NO-GO | gross +0.07R real but cost-killed; maker fills worse (adverse selection +0.29…+0.48R) |
| RSI2 / Connors pure mean-reversion | 15m/5m | NO-GO | holdout −0.19R |
| VWAP reversion | 15m/5m | NO-GO | holdout −0.27R |
| Liquidity-sweep / stop-hunt reversal (ICT/SMC) | 15m/5m | NO-GO | holdout −0.38R |
| Opening-range breakout | 15m | NO-GO | holdout −0.30R |
| Momentum continuation + trailing | 15m/5m | NO-GO | −0.40R (15m), −0.73R (5m) |
| Pullback-in-trend (RSI2 in SMA200 trend) | 1h | NO-GO | t≈−15 both halves |
| Cross-sectional momentum (long top-K/short bottom-K) | 1d | NO-GO | insignificant in-sample, holdout inverted |
| Funding-extreme directional | 8h | NO-GO | +1.6%/trade 2019-23 → negative 2023-26: regime mirage |
| Donchian below 4h | 5m→2h | NO-GO | −0.44R at 5m; weak t<1 at 1h/2h |
| Squeeze below 1h | 15m/30m | NO-GO | −0.11R / −0.05R |
| Squeeze loosened for frequency (Q20→Q50) | 1h | NO-GO | trades ×1.8 but holdout edge dies (t<0.8) |

## What DID pass (for contrast — these are swing, not scalp)

| edge | TF | net Exp-R | PF | DSR | status |
|---|---|---|---|---|---|
| donchian_trend | 4h | +0.284 | 1.37 | +2.44 | ACCEPTED 5/5 — deployed (paper) |
| squeeze_breakout | 1h | +0.088 | 1.12 | +1.58 | ACCEPTED — deployed (paper) |
| carry (funding harvest) | 8h | +4…8%/yr, t>11 | — | — | validated; engine port pending |

## Why scalp is structurally dead here (and what would reopen it)

1. **Cost floor.** Taker round trip ≈0.13–0.14%. A 15m/5m stop is 0.2–0.7%
   of price, so cost alone is 0.2–0.6R per trade. The measured gross edge of
   ANY OHLCV signal family at these horizons is ≤ +0.08R. The inequality is
   not close and holds in every campaign.
2. **Maker doesn't fix it.** Passive fills were tested: fill-ratio ~0.9 but
   the missed fills are the winners (adverse selection) — net worse.
3. **What would actually reopen scalp:** L2/tick order-flow data + latency
   infrastructure (a different system), or a fee regime several times lower.
   Neither is available. Until one is, any "scalp mode" added to this engine
   would be a measured money-loser and is refused on evidence.

**The honest fast option that survives:** squeeze @1h (~3 trades/day) plus
donchian @4h (~1.4–2/day) ≈ 4.5–5 trades/day fleet-wide with positive
expectancy — see `SYSTEM_STATE.md` §6–7 for the exact config.
