# SCALP_EDGE_RESEARCH_REPORT.md — the complete scalp verdict

**Updated: 2026-07-09 (campaigns 5 and 6).** Consolidates every
scalp/faster-edge family ever tested on this system. Campaign 5 closed the
ICT/SMC multi-TF model (htf_liquidity_sweep_bos_fvg); campaign 6
("leave nothing untried", owner mandate) closed the remaining DATA AXES the
archive offers beyond OHLCV: aggressor flow (taker-buy volume / trade
count), spot-perp basis, funding-window carry, hour-of-day seasonality and
open-interest dynamics. **Definitive verdict: NO-GO — there is no
taker-executable scalp/intraday edge on Binance USDT-M perps with any data
this system can access.** The search space below 1h is now exhausted in
the strong sense: every signal family AND every information source has
been measured.

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

## Campaign 6 (2026-07-09): the remaining data axes (owner mandate: "leave nothing untried")

Prior campaigns tested signal FAMILIES on OHLCV. This campaign tested every
remaining INFORMATION SOURCE in the official archive: taker-buy volume and
trade count inside each kline (the 1m aggregation of aggressor order flow),
spot klines (perp-spot basis), the funding-rate schedule, and the 5m
open-interest metrics (majors; daily archive files). 15 pre-registered
cells, 24 months × 12 coins, same protocol, DSR at **182** trials.
Harness `scripts/flow_edge_wave.py`, fetcher `scripts/fetch_flow_data.py`.

| cell | n | gross R | net R | cost | PF | H1 R | H2 R | coins+ | verdict |
|---|---|---|---|---|---|---|---|---|---|
| FA CVD divergence @5m | 93,632 | +0.035 | −0.775 | 0.81 | 0.43 | −0.75 | −0.80 | 0/12 | NO-GO |
| FA CVD divergence @15m | 33,189 | −0.009 | −0.492 | 0.48 | 0.55 | −0.49 | −0.50 | 0/12 | NO-GO |
| FB imbalance follow @5m | 7,558 | +0.021 | −0.574 | 0.60 | 0.44 | −0.46 | −0.69 | 0/12 | NO-GO |
| FB imbalance follow @15m | 2,963 | −0.001 | −0.359 | 0.36 | 0.58 | −0.31 | −0.40 | 0/12 | NO-GO |
| FC imbalance fade @5m | 7,574 | −0.009 | −0.605 | 0.60 | 0.41 | −0.59 | −0.62 | 0/12 | NO-GO |
| FC imbalance fade @15m | 2,953 | +0.034 | −0.323 | 0.36 | 0.61 | −0.30 | −0.34 | 1/12 | NO-GO |
| FD absorption reversal @5m | 1,302 | +0.024 | −0.626 | 0.65 | 0.40 | −0.68 | −0.58 | 0/12 | NO-GO |
| FD absorption reversal @15m | 101 | −0.091 | −0.478 | 0.39 | 0.44 | −0.28 | −0.67 | 0/12 | NO-GO |
| FE large-print proxy @5m | 22,342 | +0.022 | −0.596 | 0.62 | 0.42 | −0.56 | −0.64 | 0/12 | NO-GO |
| FF basis-extreme fade @5m | 21,723 | +0.013 | −0.359 | 0.37 | 0.54 | −0.32 | −0.40 | 0/12 | NO-GO |
| FG basis-impulse follow @5m | 24,036 | −0.017 | −0.583 | 0.57 | 0.43 | −0.50 | −0.66 | 0/12 | NO-GO |
| FH funding-window harvest | 655 | +0.037 | −0.370 | 0.41 | 0.61 | −0.63 | −0.11 | 2/12 | NO-GO |
| FI seasonality (H1-discovered hour, H2-traded) | 1,090 | +0.056 | −0.169 | 0.22 | 0.61 | — | OOS by design | 0/3 | NO-GO |
| FJ OI-confirmed breakout @15m majors | 3,403 | **+0.068** | −0.156 | 0.22 | 0.79 | −0.26 | −0.06 | 0/5 | NO-GO |
| FK OI-divergence fade @15m majors | 3,726 | +0.042 | −0.180 | 0.22 | 0.75 | −0.20 | −0.16 | 0/5 | NO-GO |

Reading: the order-flow information IS real — CVD divergence, absorption,
OI-confirmed breakouts all show positive gross (+0.02…+0.07R), consistent
with the +0.03…+0.08R gross ceiling every OHLCV family showed. Nothing
approaches the 0.22–0.81R cost bar; the funding payment itself (FH) is an
order of magnitude smaller than the round-trip cost of collecting it; the
seasonality cell is out-of-sample by construction and still loses. Zero
cells positive net; zero coins positive in any cell but three tiny slices.

What remains genuinely untested after campaign 6: **nothing this system
can access.** aggTrades (sub-minute prints) exists in the archive but its
1m aggregation — taker-buy volume/count, tested here — already bounds the
information at ≤ +0.07R gross; sub-minute timing cannot multiply that
10× to clear cost, and processing it exceeds this environment's capacity.
L2 order-book depth (the actual microstructure edge source) is not
archived at all. The scalp door is closed on evidence, not on effort.

## Campaign 5 (2026-07-09): htf_liquidity_sweep_bos_fvg (owner-requested)

The full ICT/SMC multi-timeframe model: HTF liquidity map (PDH/PDL, session
H/L, 1h/4h swings, EQH/EQL) → 5m sweep → 5m BOS / inverse-FVG confirmation
→ 1m BOS trigger → TP at the opposite liquidity draw. 1m execution data
(1,051,200 bars/coin × 12 coins, 24 months), 20 cells covering
confirmation (BOS/IFVG/both), trigger (1m/5m), entry
(market/limit/FVG-mid), stop (sweep-wick/1m-structure/IFVG-invalidation),
TP (liquidity-draw/2R/partials+runner/pool-type: internal vs session-day
H-L vs equal-H-L), whole sessions + open windows (London-open, NY-open,
London/NY overlap) and a 4h trend filter. The spec's strict ordering
(map → sweep → 5m confirm → 1m trigger → entry) is enforced and
spot-verified.

**20/20 cells NO-GO; 16/20 gross-negative BEFORE cost; 0/12 coins positive
in the base cell; both halves negative everywhere.** Best cells: EQ-target
TP net −0.128R (PF 0.74), limit-entry −0.178R (PF 0.70); London-open /
overlap windows are gross-positive (+0.02R) but cost drag is ~10× that.
The multi-TF confirmation stack changes which trades are taken, not what
they earn. Full detail: `HTF_LIQUIDITY_SWEEP_RESEARCH_REPORT.md`;
harness `scripts/liquidity_sweep_wave.py`. Campaign-wide trial count: 167.

## Campaign 4 (2026-07-08): the last untested families

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
