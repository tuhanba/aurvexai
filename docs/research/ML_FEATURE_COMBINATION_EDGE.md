# ML feature-combination edge — the last untested method (2026-07-19)

Owner mandate: *"denemediğin test veya teknik analiz kalmasın"* — leave no test
or technical analysis untried. Across eight research campaigns (215
pre-registered trials, `SCALP_EDGE_RESEARCH_REPORT.md`,
`LIVE_CONFIG_OPTIMIZATION.md` §5) every hand-crafted TA family was NO-GO after
cost except the five deployed swing legs. Exactly **one** method had never
been run: instead of hand-crafting confluence rules, feed EVERY standard TA
feature into one nonlinear learner simultaneously and let it discover any
predictive combination itself. A gradient-boosted model over ~40 features
subsumes hand-crafted confluence — **if it cannot beat cost, no TA
combination will.** This report closes that cell.

Scripts: `scripts/ml_edge_test.py` (4h/1h swing horizons),
`scripts/ml_scalp_test.py` (1m scalp horizon).

## Method (identical rigour to the promotion pipeline)

- **~40 causal OHLCV features**: lagged returns (1/2/3/5/10/20), RSI, MACD/EMA
  slopes (9/21/50), ADX + DI-diff, ATR%, Bollinger position, distance from
  10/20/50-bar channel high/low, candle shape (body, CLV, range), volume
  ratio. All computed from bars **up to and including t** — no lookahead.
- **Label**: sign of the H-bar-forward return (the holding horizon).
- **Walk-forward** with a **purge/embargo of H bars** between train and test so
  a label can never leak across the split. Model:
  `HistGradientBoostingClassifier(max_iter=120, max_depth=4, lr=0.06,
  l2=1.0)`, refit every fold.
- **Trade sim on OOS predictions**: enter when `P(up)` clears the 0.55/0.45
  band, hold H bars, exit at close; net return = directional H-bar return −
  **0.13% round-trip cost**, expressed as **R vs a 2×ATR stop** (comparable to
  the deployed book's +0.147R). Pooled across coins, per-horizon; report mean
  net R, t-stat, and the fraction of OOS folds positive.
- **GO bar**: net Exp-R clearly > 0 **and** t > 3 **and** the majority of OOS
  folds positive — i.e. it must beat the deployed swing book's honesty, not
  just zero.

## The lookahead catch (why this report exists at all)

The **first** run reported a money printer:

| tf | H | netExpR | t | pos-folds |
|---|---|---|---|---|
| 4h | 6 | **+0.559** | +244 | 100% |
| 1h | 6 | **+0.508** | **+497** | 100% |

A t-stat of +497 and 100% positive folds is not an edge — it is a bug. Real
market edges live near +0.05–0.15R with t of single digits; anything an order
of magnitude larger is leakage, not alpha. Traced to a single line: two
trailing means were computed with `np.convolve(x, ones/w, mode="same")`, which
is **centred** — each output point averages `w/2` bars into the *future*. The
`bbpos` and `vr` features therefore carried tomorrow's information into
today's row. Fixed with an explicit causal trailing mean:

```python
def _trail_mean(x, w):                 # average of the last w bars, causal
    cs = np.cumsum(np.insert(x, 0, 0.0))
    out = np.zeros(n)
    for i in range(n):
        lo = max(0, i - w + 1)
        out[i] = (cs[i + 1] - cs[lo]) / (i + 1 - lo)
    return out
```

This is the project's core discipline in miniature: **a result too good to be
true is a bug to be found, not an edge to be shipped.** The same no-lookahead
vigilance that killed the earlier paginator leak killed this one.

## Results (lookahead-fixed — the honest read)

**Swing horizons — 4h & 1h, 11 coins:** edge collapses to negative once the
leak is removed.

```
===== ML feature-combo edge — 4h bars, 11 coins =====
  H= 1 bars  netExpR=-0.0320  t=-23.28  pos-folds= 5%  NO-GO
  H= 3 bars  netExpR=-0.0312  t=-13.03  pos-folds=21%  NO-GO
  H= 6 bars  netExpR=-0.0267  t= -8.08  pos-folds=36%  NO-GO
  H=12 bars  netExpR=-0.0133  t= -2.88  pos-folds=48%  NO-GO

===== ML feature-combo edge — 1h bars, 11 coins =====
  H= 1 bars  netExpR=-0.0648  t=-102.71 pos-folds= 1%  NO-GO
  H= 3 bars  netExpR=-0.0633  t=-60.58  pos-folds= 8%  NO-GO
  H= 6 bars  netExpR=-0.0622  t=-43.06  pos-folds=20%  NO-GO
  H=12 bars  netExpR=-0.0577  t=-27.83  pos-folds=34%  NO-GO
  H=24 bars  netExpR=-0.0557  t=-18.29  pos-folds=39%  NO-GO
```

**Scalp horizon — 1m, 5 majors, 1.3M bars/coin, 2024-01..2026-06:** deeply,
unambiguously negative.

```
===== ML feature-combo SCALP edge — 1m bars, 5 coins =====
  H=  5m  n=2147326  netExpR=-0.9419  t=-1030.98  pos-folds=0%  NO-GO
  H= 15m  n=2954410  netExpR=-0.9337  t= -842.87  pos-folds=0%  NO-GO
  H= 30m  n=3266951  netExpR=-0.9343  t= -658.08  pos-folds=0%  NO-GO
  H= 60m  n=3559785  netExpR=-0.9378  t= -487.54  pos-folds=2%  NO-GO
```

At 1m the round-trip cost is nearly a full R by itself (the 2×ATR stop is tiny
relative to 0.13%), so the model has to be right about direction *and* clear a
cost wall the size of the whole move on every trade. It cannot: ~−0.94R,
t ≈ −500 to −1030, essentially 0% positive folds across 2–3.5M OOS trades.

## Verdict — NO-GO everywhere; scalp is closed for good

The single genuinely untested method — a joint ML feature-combination model —
**fails to beat cost at every horizon**, from 4h swing (−0.01 to −0.03R) to 1h
(−0.06R) to 1m scalp (−0.94R). This is fully consistent with, and independently
confirms, the 215-trial NO-GO base: the structural reason is unchanged —

> gross edge ceiling ≈ +0.07R; taker round-trip cost 0.13% = 0.2–0.6R at scalp
> stops. **Cost > gross edge.** A learner combining every signal raises gross
> edge marginally but never lowers cost, and the axes aren't independent.

Nonlinear ML does not rescue it — it confirms it, with the strongest
statistical signal in the entire research program (t ≈ −1000 at scalp).

**TA adequacy is now exhaustive.** The `LIVE_CONFIG_OPTIMIZATION.md` §5 line
"one ML-scalp cell open (offered)" is closed: **run, NO-GO.** There is no
untried test or technical-analysis method left that serves this system's
purpose. The edge is the five-leg swing book; scalp reopens only with a
structural change (materially lower fees, or L2/tick data + latency infra),
never a modeling trick.

## Reproduce

```
python scripts/ml_edge_test.py      # 4h + 1h swing horizons (~5 min)
python scripts/ml_scalp_test.py     # 1m scalp horizon (~35 min, 1.3M bars/coin)
```
