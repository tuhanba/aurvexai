# Live-config optimization — the definitive read (2026-07-19)

Owner mandate: don't stop until the optimal **daily target %, risk %,
leverage, trade count** and **TA adequacy** are settled with data, not
intuition. Scripts: `joint_optimize.py`, `daily_target_optimize.py`,
`live_config_optimize.py` (real 5-leg OOS trade stream, 7944 trades, 5.69y,
day-block bootstrap, net of cost). Honest confidence level stated per item.

## 1. Leverage — **SETTLED (not a return variable)**

In this engine leverage only sets how much margin a risk-sized notional
locks; return and risk are unchanged (`RISK_MODEL.md`). It is set by the
efficient liq-safe policy and bounded by `LIQ_SAFETY_BUFFER=2` (the stop
always fires before the modelled liquidation). There is nothing to optimize
— higher leverage = less locked margin, same P&L; the safety bound is the
only constraint and it is correct. **Keep `LEVERAGE_POLICY=efficient`.**

## 2. Trade count — **SETTLED (at max Σ total R)**

Compound growth is driven by Σ(total R) = n·Exp-R, not by trade count or
risk alone. The book is already at that maximum for the surviving edges:
squeeze@1h was retired (+0.018R × 4031 = pure variance, crowding better
legs) and squeeze@2h added (+0.065R × 2041 = +132R real fuel). donchian +
ichimoku carry 72% of the fuel. **More frequency only helps while Exp-R
stays clearly positive — we are at the max.** The next frequency step
(more concurrent positions) is the slots/exposure lever, gated on the
`/capacity` data, not more legs.

## 3. Risk % — **BRACKETED [1.0–1.5%]; keep 1.5%, do NOT raise**

Two independent models bracket the optimum and disagree on the exact point:
- **Per-trade Kelly** (`joint_optimize`): full Kelly f\* ≈ 5.8%, half-Kelly
  ≈ 2.9% → 1.5% is *below* half-Kelly = conservative, room UP.
- **Per-day variance** (`live_config_optimize`, bootstrap): the ~4.5
  trades/day create high daily variance; geometric drag favours *lower*
  risk (0.5% is the least-drawdown row).

The truth sits between and depends on real concurrency/correlation
(avg leg corr +0.05, near-independent). Honest read: **keep 1.5%** (the
validated deployed value), **do not raise it**, and know the book carries
**40–70% drawdowns regardless** — inherent to a low-win-rate (31–38%)
runner strategy. If those drawdowns are intolerable, 1.0% roughly halves the
drawdown for less-than-proportional growth loss. The paper window refines
this with live data.

## 4. Daily target % — **STRONG SIGNAL, NOT yet actionable (model limitation)**

Both models show the fixed **+4% daily flatten CAPS the skew edge**: at
every risk level no-flatten beats the best flatten config (deployed 1.5%/+4%
MAR −0.89 vs 1.5%/no-flatten MAR +17.74 in the model). donchian+ichimoku
make money from a few big *runner* days; a +4% daily cap truncates exactly
those, while losing days run to −10%.

**But — the honest limitation that stops me short of "drop it":** these
models use CLOSED-trade R and are **blind to the flatten's actual
mechanism** — it fires on *intraday mark-to-market* equity, locking a peak
before it reverses. A day that hits +8% MTM at noon then closes at +1% is
banked at the target by the flatten but shows +1% to my closed-R model. So
the model sees the flatten's *capping harm* but not its *peak-lock benefit*.
The net is genuinely uncertain from this analysis.

**Resolved (2026-07-20) → `DAILY_PROFIT_LOCK_PCT` raised 4 → 8.** The deployed
flatten is *adaptive* (4% floor → 10% ceiling by BTC-4h-ADX), so the fixed-4%
picture above was too pessimistic; replaying the true adaptive mechanism on the
real stream (`ADAPTIVE_PROFIT_FLOOR.md`, `scripts/adaptive_floor_sweep.py`)
shows raising the floor is **monotonically better** (MAR −0.55 @4% → −0.29 @8%
→ −0.19 @10%; no-flatten best at +20 but model-blind to peak-lock). Floor 8% is
the low-regret, reversible middle: it halves the modelled capping harm while
keeping the peak-lock flatten (fires later, not never). The DEFINITIVE
resolution — whether to drop the flatten entirely — needs the paper window,
which logs every flatten event and the subsequent path. **Do not wholesale-drop
the owner's flatten on model evidence blind to half its mechanism.**

## 5. TA adequacy — **SETTLED (exhaustive; the last ML cell is now run — NO-GO)**

**215 pre-registered trials** across 25 signal families and every
archive-accessible information source, all NO-GO after cost except the 5
deployed swing legs:
- OHLCV families 5m→1d (momentum, reversion, breakout, sweep/ICT, ORB,
  leader-lag, inside-bar, retest, …) — NO-GO.
- Every non-OHLCV data axis: aggressor flow (CVD, absorption, large-print),
  spot-perp basis, funding windows, hour seasonality, open interest — 15/15
  NO-GO (campaign 6).
- **Composite/combined** signals: EMA+Supertrend+Ichimoku confluence
  (`composite_wave`) and combined flow at 5m/15m (`flow_edge_wave`) — NO-GO.
- Full ICT/SMC multi-TF model (1m execution) — 20/20 NO-GO; swing ICT @4h —
  4/4 NO-GO (campaign 8).

Structural reason: gross edge ceiling ≈ +0.07R; taker round-trip cost
0.13% = 0.2–0.6R at scalp stops. **Cost > gross edge — combining signals
raises gross marginally but never lowers cost, and the axes aren't
independent.** The only genuinely untested method was a *joint ML
feature-combination model* — a gradient-boosted learner over ~40 causal
features, which subsumes hand-crafted confluence. **It has now been run and is
NO-GO at every horizon** (4h −0.01/−0.03R, 1h −0.06R, 1m scalp −0.94R;
`ML_FEATURE_COMBINATION_EDGE.md`) — the strongest statistical signal in the
whole program (t ≈ −1000 at scalp), confirming rather than rescuing the cost
bound. Scalp reopens only with **materially lower fees or L2/tick data +
latency infra** — structural, not a modeling trick.

## Bottom line for live

| dimension | verdict | action |
|---|---|---|
| leverage | settled — return-neutral | keep efficient policy |
| trade count | settled — max Σ total R | keep 5 legs; frequency via /capacity data |
| risk % | bracketed [1.0–1.5%] | keep 1.5%, don't raise; expect 40–70% DD |
| daily target | resolved (adaptive-aware) | floor raised 4→8% (applied); full drop deferred to paper window |
| TA | exhaustive (215 trials + ML feature-combo, all NO-GO) | swing book is the edge; the last ML cell is now run and closed |

Nothing changed in the engine — measurement only. The one config change with
a real evidence base and low regret is raising `DAILY_PROFIT_LOCK_PCT` from 4
toward 6–8%; the risk % and the flatten's full resolution belong to the
paper window.
