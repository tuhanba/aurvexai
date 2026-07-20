# REGIME_ADAPTIVE_PORTFOLIO_IMPLEMENTATION.md

**Regime-Adaptive Multi-Edge Portfolio Engine — implementation plan for Claude Code**

Author: system owner review · Date: 2026-07-20 · Status: **Phase 1 IMPLEMENTED
(observational, flag-gated OFF)**; Phases 2–8 pending. This file is the single
source of truth for the build. Read it top to bottom before touching code.

## Build progress

- **Phase 1 — DONE (this PR).** Observational multi-dimensional regime ensemble.
  New: `src/aurvex/regime.py` (`RegimeEnsemble`, `RegimeState`, dimensions
  trend/vol/breadth/corr/liq, confidence, persistence, transition risk,
  hysteresis, PANIC override, fail-safe). Additive DB migrations
  (`regime_history`, `policy_versions`, trades audit columns). Config flags
  (all default OFF/neutral). Engine wiring: `_evaluate_regime()` stores a
  `RegimeState` per cycle and stamps observational context onto decisions/
  trades; **`_market_regime()` and `decide()` are untouched** so sizing is
  byte-identical. Read-only `/api/regime` surface. Tests: `test_regime_ensemble`
  (14), `test_regime_parity` (5), `test_regime_dashboard` (3). Full suite
  **846 passed**. Nothing changes a decision until `REGIME_ENSEMBLE_ENABLED` is
  turned on, and even then Phase 1 only observes.
- **Phases 2–8 — pending**, per §26. Each decision-changing phase must pass its
  §18 acceptance gate (backtest) then paper confirmation before it arms.

> **Prime directive.** This is an *additive support layer*, not a rewrite.
> `DecisionEngine.decide()` stays byte-identical (paper/live/backtest parity is
> sacred — `PAPER_LIVE_PARITY.md`). Everything new is (a) observational first,
> (b) flag-gated default-OFF, (c) measured before it is allowed to change a
> decision, (d) phased with per-phase acceptance gates. Nothing here weakens a
> live gate, raises per-trade risk above half-Kelly, dilutes the coin-specific
> edge, or reopens scalp.

---

## 1. Executive summary

### 1.1 Is the imagined system technically feasible?
**Yes — and ~40% of it already exists** in a minimal form. The engine already
has: one shared decision brain, a 1-D BTC-4h-ADX regime signal
(`Engine._market_regime`), a regime×edge risk *multiplier*
(`_regime_edge_multiplier`, `REGIME_EDGE_WEIGHT_ENABLED`), an adaptive daily
profit target (`_effective_profit_pct`), a two-pass global ranking allocator
with correlation-cluster / same-side caps (`allocation.py`, currently OFF), a
cost-inclusive risk model, an efficient-leverage solver, an observe-first
shadow learner with a counterfactual A/B table (`shadow_ab`), and a
funnel/observability spine. The missing piece is not raw capability — it is a
**central controller** that turns a *multi-dimensional* regime read into a
*coherent joint setting* of risk budget, slots, exposure, universe, correlation
caps and profit protection, all measured per regime.

### 1.2 The honest strategic answer — real scalp vs regime-multi-edge
**Build the regime-aware multi-edge portfolio engine. Do NOT build a scalp
engine.** The evidence is definitive and must not be re-litigated without new
data: 25 signal families / 95+ cells across six campaigns AND every archive
data axis beyond OHLCV (aggressor flow, basis, funding windows, seasonality,
OI) are all net-negative after cost (`SCALP_EDGE_RESEARCH_REPORT.md`,
`SYSTEM_STATE.md §3`). The structural reason is a cost > gross-edge inequality,
not a parameter miss: gross OHLCV edge at sub-1h ≈ +0.03…+0.08R; taker
round-trip ≈ 0.13–0.14% = 0.2–0.6R at scalp stops. A real scalp needs
L2/tick data + low-latency infra this system does not have. The safe way to
*more trades* is **more independent positive edges, allocated by regime** —
exactly this plan — not faster direction-calling. (§2 re-audits this with the
specific execution-cost questions the brief asked.)

### 1.3 Where the measured upside comes from (no fantasy)
Three grounded levers, all already measured (`PORTFOLIO_FRONTIER_REPORT.md`):
1. **Regime-weighted allocation** — trend days earn +4.11 R/day @Sharpe 1.70 vs
   chop +3.16 @1.07 (**+0.95 R/day**, +35% H2 Sharpe holdout-validated). This
   is the single highest-confidence lever and the spine of this plan.
2. **Edge-weighting the book** toward the high-Sharpe legs (ichimoku 2.17,
   squeeze@4h 1.95) and away from the weak ones. Partly deployed; this plan
   makes it *regime-conditioned* and *drift-corrected*.
3. **Carry** (uncorrelated, +0.07 book corr) — out of scope here (needs its own
   engine port) but noted as the true diversifier.
There is **no** "+4%/day" here. A Sharpe-1.35 book has good and bad days that
net positive; the daily-target logic (§14) is *profit protection*, never a
production quota.

### 1.4 Biggest risk
**Over-fitting the regime model and reacting to noise.** A wrong regime label
that flips per candle, or a per-regime edge table fit to a thin sample, will
degrade a book that is currently healthy. Mitigations are load-bearing:
observe-first phasing, hysteresis, regime *confidence*, minimum-sample
Bayesian shrinkage, parameter-plateau selection, and a hard fail-safe to the
current baseline profile when regime data is missing/stale/low-confidence.

---

## 2. Current system analysis (verified against the code)

### 2.1 How regime is measured today
`Engine._market_regime()` (`engine.py:702`): fetches `REGIME_SYMBOL`
(BTC/USDT:USDT) on `REGIME_TF` (4h), computes ADX(14) on closed bars, maps it
linearly `[REGIME_ADX_LO=20, REGIME_ADX_HI=40] → [0,1]`. Cached
`REGIME_REFRESH_SEC=900`. Fail-soft: any error keeps the last value or returns
score 0 (chop). **It is 1-dimensional (trend strength only), single-symbol, no
confidence, no persistence, no transition risk, no hysteresis.**

### 2.2 What regime actually changes today
| Lever | Mechanism | Flag (default) |
|---|---|---|
| Daily profit target % | `_effective_profit_pct`: scales floor 4% → ceiling 10% by regime score | `DAILY_PROFIT_ADAPTIVE=true` (deployed) |
| Per-entry risk multiplier | `_regime_edge_multiplier` = `(1+REGIME_TILT·(2·score−1)) × edge_weight(setup)`; clamped [0.5,1.5] | `REGIME_EDGE_WEIGHT_ENABLED=true` (deployed) |

That is the entirety of regime's influence. `edge_weight` reads the **static**
`_LEG_EDGE_SHARPE` prior (`engine.py:61`).

### 2.3 What is still fixed (the gap)
Active strategies (`STRATEGIES` env, static), coin universe (`UNIVERSE_INCLUDE`
17 pinned + per-leg `u=`, static), `MAX_OPEN_TRADES=6`,
`MAX_PORTFOLIO_EXPOSURE_PCT=300`, `MAX_LEVERAGE=10`, entry threshold, cooldowns,
`MAX_DAILY_LOSS_PCT=10`, correlation caps (`MAX_PER_CLUSTER=0`,
`MAX_SAME_SIDE=0`, `MAX_CLUSTER_EXPOSURE_PCT=0` — all OFF), slot count. None of
these move with the market.

### 2.4 Where the risk multiplier is applied
Engine `_risk_modulation` (`engine.py:812`) composes `m_shadow · m_score ·
m_regime`, clamps [0.5,1.5], passes it as `risk_multiplier` into the shared
`decide()` → `RiskManager.evaluate` (`risk.py:156`), which scales `risk_amount
= balance · risk_pct/100 · risk_multiplier` and re-clamps. **Sizing only; never
gates.** Every hard cap binds *after* the multiplier.

### 2.5 How leverage/margin resolve
`RiskManager._solve_leverage` (`risk.py:293`), `LEVERAGE_POLICY=efficient`:
`lev = floor(1 / (LIQ_SAFETY_BUFFER·stop_dist_frac + MAINT_MARGIN_RATE))`,
capped at `MAX_LEVERAGE` and available margin. Notional is sized from
risk/stop *first*; leverage only sets locked margin. **Weaknesses:**
`MAINT_MARGIN_RATE=0.005` is a single flat value (no Binance maintenance-margin
*tiers*), funding cost is not added to holding cost in the live sizing path
(`FUNDING_RATE_8H` is a backtest input only), `FREE_MARGIN_RESERVE_PCT=20` is
static (not regime-aware), and there is no notional→tier feedback for large
positions.

### 2.6 How the universe is selected
`UniverseScanner.scan()` (`scanner.py`): volume-rank → apply
include/exclude → head-pin `UNIVERSE_INCLUDE` → truncate to `UNIVERSE_SIZE`.
Per-leg `u=` (`StrategySpec.universe`) restricts a leg to its validated coins.
**Static; no regime/liquidity/relative-strength conditioning.**

### 2.7 Global ranking & correlation
`allocation.py`: two-pass. Pass 1 scans + ranks by `RANK_KEY=edge` (measured
score-bucket avg_r). Pass 2 `apply_caps`: `max_open_trades` (always),
`max_per_cluster` / `max_same_side` (OFF). `CORRELATION_CLUSTERS` is a **static
hand-map** (BTC/ETH→crypto_major, etc.), and it does **not** cover the full
17-coin universe. No rolling correlation, no tail correlation, no directional
net-exposure accounting.

### 2.8 Portfolio open risk
There is **no** portfolio-level open-stop-risk sum. The only aggregate controls
are the **notional** exposure cap (MTM, `engine.py:884`) and the count cap. The
correlation-adjusted open risk the brief asks for does not exist.

### 2.9 Daily profit lock vs regime
`_daily_profit_target_guard` (`engine.py:1665`): mark-to-market flatten at
`base · _effective_profit_pct/100`, plus an optional giveback guard. Regime
scales the *target level*. Open trades are otherwise untouched by regime.

### 2.10 What happens to open trades on a regime change
**Nothing.** Regime is read at *entry* (sizing) and for the *daily target*.
There is no re-evaluation of open positions, no exit-urgency change, no
"old-regime strategies stop entering". This is a genuine gap (§15).

### 2.11 Engine fit for a central controller
Good. The engine already has the per-cycle hooks the controller needs:
`_cycle()` builds `pf` once, ranks candidates once (`cycle_buckets`), and
applies caps once. A `PortfolioController` computed **once per cycle** (like
`_market_regime` is cached) slots in cleanly alongside `_risk_modulation` and
`apply_caps` without touching `decide()`.

### 2.12 Shadow / counterfactual infra that already exists
`ShadowLearner` tracks paper + rejected signals, resolves TP/SL, buckets by
score, and **already writes a counterfactual A/B row** (`shadow_ab` table with
`risk_multiplier_would_be`, `score_delta_would_be`, `actual_net_r`) on every
resolve (`shadow.py:238`). This is the seed for the counterfactual engine (§16)
— extend it, don't rebuild it.

---

## 3. Explicit gap list (what is genuinely missing)

| # | Missing capability | Exists? | Target module |
|---|---|---|---|
| G1 | Multi-dimensional regime **ensemble** (trend + vol + breadth + correlation + liquidity) | 1-D trend only | `regime.py` (new) |
| G2 | Regime **confidence / persistence / transition risk / hysteresis** | none | `regime.py` |
| G3 | **Daily Opportunity Score** | none | `portfolio.py` (new) |
| G4 | **Strategy×Regime edge matrix** (measured, not a single Sharpe prior) | static `_LEG_EDGE_SHARPE` | `regime_matrix.py` (new) + harness |
| G5 | **Dynamic coin universe** by regime/liquidity/RS (within validated set) | static | `portfolio.py` + `scanner.py` |
| G6 | **Portfolio risk budget** (correlation-adjusted open risk, daily budget) | notional+count only | `portfolio.py` |
| G7 | **Correlation/cluster controller** (rolling corr, net directional, tail) | static caps OFF | `correlation.py` (new) |
| G8 | **Dynamic slots / exposure** by regime & opportunity | static | `portfolio.py` |
| G9 | **Incremental trade value / slot replacement / opportunity cost** | none | `portfolio.py` |
| G10 | **Regime transition management** on open trades | none | `engine.py` + `portfolio.py` |
| G11 | **Leverage/margin solver** upgrades (MM tiers, funding, regime reserve) | flat MM, no funding | `risk.py` |
| G12 | **Counterfactual policy engine** (beyond the single A/B row) | partial (`shadow_ab`) | `shadow.py` |
| G13 | **Policy versioning** stamped on every trade | none | `config.py` + `storage.py` |
| G14 | **Drift detection** state machine | none | `drift.py` (new) |
| G15 | **Return decomposition** attribution | none | `edge_analysis.py` |
| G16 | **Explicit fail-safe** to baseline profile on regime failure | fail-soft-to-neutral only | `regime.py` + `portfolio.py` |
| G17 | **Dashboard/Telegram** regime & allocation panels | minimal (regime score only) | `dashboard/app.py`, `telegram.py` |

---

## 4. Target architecture

```
Market Data (provider)
    │
    ▼
RegimeEnsemble.evaluate()  ──►  RegimeState {labels, confidence, persistence,
    │  (regime.py, cached/cycle)      transition_risk, hysteresis-stable}
    ▼
PortfolioController.plan(regime, pf, candidates)  (portfolio.py, once/cycle)
    │   ├─ DailyOpportunityScore
    │   ├─ StrategyRegimeAllocator  (active/passive/shadow legs + weights)
    │   ├─ DynamicUniverse          (eligible coins ∩ validated set)
    │   ├─ PortfolioRiskBudgeter    (daily + correlation-adjusted open risk)
    │   ├─ CorrelationController     (cluster / net-directional / tail caps)
    │   └─ SlotExposurePlan          (max_open, exposure cap this cycle)
    ▼
PortfolioPlan  ──►  feeds the EXISTING engine support layer:
    │   • risk_multiplier  → _risk_modulation → decide(risk_multiplier)  [UNCHANGED brain]
    │   • rank tilt        → allocation.rank_signal
    │   • dynamic caps     → allocation.apply_caps (max_open/cluster/same_side)
    │   • universe gate    → scanner working set
    │   • incremental value→ apply_caps admission test
    ▼
DecisionEngine.decide()  ── BYTE-IDENTICAL, no regime knowledge ──►  Decision
    ▼
PaperExecutor / (gated) LiveExecutor
    ▼
Journal + Shadow(+counterfactual) + Funnel + Storage (policy_version stamped)
    ▼
DriftMonitor  ──►  ACTIVE → REDUCED → SHADOW_ONLY → REVIEW  (per leg/regime)
    ▼
Dashboard / Telegram (regime, opportunity, budget, attribution)
```

**Parity rule (non-negotiable):** the controller is *engine-support* only. It
produces (a) a `risk_multiplier` (already a parity-safe `decide()` arg), and
(b) engine-level slot/cap/universe decisions that are already applied
identically in paper/live (they gate *whether the engine calls the executor*,
never *what `decide()` returns*). The regime read must be reproducible in
backtest via a `RegimeProvider` interface so walk-forward validation uses the
same code.

---

## 5. Regime model specification

### 5.1 Design choice — explainable weighted ensemble
Compared options: fixed rules, score ensemble, HMM, clustering, Bayesian, and
supervised classification. **Chosen: a transparent per-dimension score ensemble
with hysteresis.** Rationale matching the repo's philosophy (`CLAUDE.md`
"keep it simple", measurable, no ML hard gates): HMM/clustering/supervised
models are opaque, need labels or converge unstably on 6y of one asset, and are
overfit-prone. A weighted ensemble of *individually validated, individually
disableable* sub-signals is auditable, degrades gracefully, and each dimension
can be turned off if it fails to add measurable value. **Complexity is added
only where a dimension proves out-of-sample lift over the 1-D trend baseline.**

### 5.2 Sub-models (each 0..1, each independently gated)
| Dim | Signal | Feature | Source (exists) |
|---|---|---|---|
| **Trend** | BTC-4h ADX(14) + EMA(50/200) slope | `[20,40]→[0,1]`, slope sign confirm | `indicators.adx`, `ema` (exists) |
| **Volatility** | ATR(14) percentile over trailing 180 bars **and** BB(20,2) bandwidth percentile | high pct = expansion | `indicators.atr`; BB from `indicators` |
| **Breadth** | fraction of universe above its own EMA50 (adv/decl proxy) | `n_up / n_total` on 4h closed bars | universe snapshots (engine already fetches) |
| **Correlation** | mean pairwise rolling return corr across universe (30-bar) | high = correlation-shock risk | `correlation.py` (new) |
| **Liquidity** | median 24h quote-vol percentile + median spread | low vol / wide spread = stressed | `snap.quote_volume_24h`, `orderbook.spread_pct` (exist) |

Each dimension returns `(state_label, sub_score∈[0,1], data_ok∈bool)`.

### 5.3 Composite regime label (deterministic mapping)
A small, auditable rule table maps the vector → a coarse label. Start with the
essential set (add others only if measured):

```
STRONG_TREND       trend≥0.66 & breadth≥0.5 & corr<0.75
WEAK_TREND         0.33≤trend<0.66
CHOP               trend<0.33 & vol<0.6
VOL_EXPANSION      vol≥0.8 & trend<0.66
VOL_COMPRESSION    vol≤0.2
PANIC              vol≥0.9 & breadth≤0.2 & corr≥0.8   (down-fast, everything correlated)
TREND_WITH_CORR_RISK  trend≥0.66 & corr≥0.75          (the "6 correlated longs" trap)
TRANSITION/UNCERTAIN  confidence<CONF_MIN or hysteresis pending
```
`RECOVERY`, `RISK_ON_ALT`, `BTC_DOMINANT`, `CORRELATION_SHOCK` are **deferred**
— add each only when §7's matrix shows it selects a materially different, still
positive allocation. Do not ship labels the allocator does not use.

### 5.4 `RegimeState` output (the contract)
```python
@dataclass(frozen=True)
class RegimeState:
    label: str                     # composite label above
    confidence: float              # 0..1 (§6)
    sub_scores: dict               # {"trend":.., "vol":.., "breadth":.., "corr":.., "liq":..}
    sub_labels: dict               # per-dim human labels
    persistence_bars: int          # bars the label has held
    prev_label: str
    transition_risk: float         # 0..1 (§6)
    data_ok: bool                  # False → engine fail-safe to baseline (§17)
    features_used: list            # which dims contributed (audit)
    reason: str                    # short human explanation
    ts: int
```

### 5.5 Guard rails
- Any dim with `data_ok=False` is dropped from the composite and reduces
  confidence; if **trend** (the anchor) is unavailable, `data_ok=False` overall.
- All sub-signals read **closed bars only** (`snap.closed_ltf`) — no lookahead.
- Cached and recomputed at most every `REGIME_REFRESH_SEC` (reuse the existing
  cadence; regime is a slow variable).

---

## 6. Feature list & confidence / transition / hysteresis

### 6.1 Confidence
```
raw_conf = 1 - dispersion(sub_scores among *agreeing* dims)
data_conf = fraction_of_dims_with_data_ok
confidence = raw_conf * data_conf * persistence_factor
persistence_factor = min(1, persistence_bars / CONF_PERSIST_BARS)   # default 3
```
Low confidence → the controller behaves more conservatively (§7.3) and, below
`CONF_MIN` (default 0.35), the label collapses to `TRANSITION/UNCERTAIN`.

### 6.2 Transition risk
```
transition_risk = clamp01(
      w1 * |trend_now - trend_prev_window|          # trend velocity
    + w2 * vol_sub_score                            # high vol → unstable
    + w3 * (1 - persistence_factor)                 # young regime
    + w4 * corr_sub_score )                         # correlation building
```
High transition risk → shrink risk budget and slots even if the current label
is favourable (a strong trend about to break is dangerous).

### 6.3 Hysteresis (whipsaw guard) — **load-bearing**
- **Asymmetric thresholds:** entering a regime needs the score to cross the
  *high* threshold; leaving it needs a cross of the *low* threshold
  (Schmitt-trigger). Defaults e.g. trend enter ≥0.66, exit <0.55.
- **Minimum persistence:** a new label must hold for `REGIME_CONFIRM_BARS`
  (default 2 closed regime-TF bars) before it becomes the *effective* label.
  Until confirmed, effective label = previous label, and state =
  `TRANSITION/UNCERTAIN` for allocation purposes.
- **Override:** a `PANIC` classification bypasses confirmation (react
  immediately to a crash), gated by `REGIME_PANIC_IMMEDIATE=true`.

### 6.4 Which features are worth it vs not (honest pre-registration)
- **Keep (measurable, cheap, already available):** BTC-ADX trend, ATR/BB
  volatility, breadth (universe-vs-EMA), rolling correlation, liquidity.
- **Defer / probably not worth it now:** funding distribution, OI change,
  basis, liquidation flow — campaign 6 proved these carry ~+0.02–0.07R gross
  as *entry* signals (dead after cost). As *regime context* they *might* add
  value, but only add them in a later phase if §7's matrix shows OOS lift.
  **Do not add a data feed the allocator cannot demonstrably use.**

---

## 7. Strategy–regime matrix specification

### 7.1 What it replaces
The static `_LEG_EDGE_SHARPE` prior (`engine.py:61`), which the 2026-07-17 leg
review already flagged as **stale** (it overweights donchian 1.06 though
donchian is ≈0 in 2025+). Replace the single-number prior with a
**measured (leg × regime) → weight** table plus a drift-corrected refresh.

### 7.2 Measurement (harness, NOT assumptions)
New harness `scripts/regime_matrix.py` (built on the existing
`scripts/leg_review.py` + `scripts/portfolio_frontier.py` machinery, which
already replay real Binance archive klines through the real engine exits with
DSR deflation). For every deployed leg × every regime label, on 6y (11-coin
long-history) + deployment-frame slices, measure:
trades, net Exp-R, win%, PF, daily Sharpe, MaxDD, avg R, median R, holding
time, worst losing streak, cost sensitivity, and per-coin breakdown. Output a
JSON table `data/regime_matrix.json` consumed at runtime.

### 7.3 Weight derivation (from the matrix, shrinkage-guarded)
```
edge_weight(leg, regime) =
    1 + EDGE_WEIGHT_STRENGTH * (2*z - 1)
z = bayes_shrunk_rank( sharpe(leg,regime), N=trades(leg,regime), prior=global_sharpe(leg) )
```
- **Shrinkage:** thin cells (N < `REGIME_MATRIX_MIN_N`, default 150) shrink
  toward the leg's global weight — never let a 20-trade cell dominate.
- **Active / passive / shadow-only per regime:**
  - `active` if net Exp-R > +cost-bar AND DSR>0 in that regime,
  - `passive` (weight floored, no new entries) if ≈0,
  - `shadow-only` if measured negative in that regime (observe, never trade).
- **Confidence scaling:** `effective_weight = 1 + confidence·(edge_weight−1)` —
  low regime confidence pulls all weights toward neutral 1.0.

### 7.4 Illustrative shape (to be *filled by measurement*, not shipped as-is)
| Leg | Strong Trend | Weak Trend | Chop | Vol Expansion | Panic |
|---|---|---|---|---|---|
| ichimoku@4h | active↑ | active | passive | active | shadow |
| squeeze@4h | active | active | passive | active↑ | shadow |
| donchian@4h | active | passive | shadow | active | shadow |
| band_walk@4h | active | active | passive | active | shadow |
| squeeze@2h | active | passive | shadow | active | shadow |
**These cells are placeholders.** The harness fills them. Ship only what the
harness measures positive.

---

## 8. Dynamic universe specification

**Iron rule:** the universe can only ever **narrow** from the validated superset
(`UNIVERSE_INCLUDE` 17 + each leg's `u=` set). It may **never** add a coin that
was not edge-validated — the edge is coin-specific (`PORTFOLIO_FRONTIER_REPORT`,
`SYSTEM_STATE §6`). Dynamic universe = *disqualification within the validated
set*, never expansion.

### 8.1 Per-cycle eligibility (a coin must pass ALL)
```
eligible(coin, regime) =
    coin ∈ leg.validated_universe                    # hard: validated set only
  & quote_vol_24h ≥ liq_floor(regime)                # regime-tightened liquidity
  & spread_pct ≤ spread_ceiling(regime)              # regime-tightened spread
  & (regime not in {PANIC} or coin ∈ MAJORS)         # panic → majors only
  & rolling_corr_ok(coin, open_book)                 # correlation admission (§10)
```

### 8.2 Regime-conditioned floors (measured, not guessed)
| Regime | Universe shape |
|---|---|
| Strong/Weak Trend | full validated set; optional relative-strength tilt (rank by RS, keep top-K) |
| Chop | narrow to coins with *measured* positive chop-regime edge (from §7 matrix); if none, **trade nothing** that leg |
| Vol Expansion | full set, tighter spread ceiling |
| Panic | BTC/ETH + top-liquidity majors only; spread/slippage ceilings tightened; smaller notional (§12) |
| Vol Compression / Uncertain | reduced set, fewer slots |

`liq_floor` / `spread_ceiling` per regime are **config with measured defaults**
— derived from the historical spread/liquidity distribution during each regime,
not invented.

### 8.3 Minimum-data guard
A coin is only added/removed on a regime basis if there are ≥
`UNIVERSE_MIN_SAMPLE` resolved trades for (coin × regime) or an explicit
config; **never** react to the last few trades (mirrors the shadow-learner
minimum-sample discipline).

---

## 9. Portfolio risk formulas

### 9.1 The objective (documentation of intent; not solved live)
```
maximize  E[log-growth]
        − λ_dd · Drawdown_penalty
        − λ_corr · Correlation_penalty
        − λ_cost · Cost_penalty
        − λ_unc · Regime_uncertainty_penalty
        − λ_ruin · Ruin_penalty
```
This is the *design north star* (Objective Hierarchy §L below). The **live**
implementation is a bounded, explainable approximation — never a black-box
optimiser (no Optuna auto-apply; `CLAUDE.md` non-negotiable #5).

### 9.2 Objective hierarchy (hard priority order — the tie-breaker)
1. Capital preservation → 2. positive post-cost expectancy → 3. low
risk-of-ruin → 4. robust OOS performance → 5. controlled drawdown → 6.
risk-adjusted growth → 7. capital/margin efficiency → 8. trade frequency →
9. daily target. **The daily target never overrides 1–8.**

### 9.3 The per-entry multiplier (extends the existing composition)
```
effective_risk_pct = base_risk_pct(1.5)
    × m_regime_edge      # (§7) regime × leg edge weight, confidence-scaled
    × m_opportunity      # (§13) daily opportunity score band
    × m_confidence       # regime confidence (low → <1)
    × m_transition       # 1 − k·transition_risk
    × m_drawdown         # equity-drawdown throttle
    × m_correlation      # (§10) correlation-adjusted down-weight
    × m_shadow × m_score # EXISTING measured-edge modulation
clamp to [0.5, 1.5]  → then RiskManager re-clamps to the [MIN,MAX] risk band
```
Every factor: **source, formula, bounds, data-need, fail-safe** in the table
below. `base_risk_pct` stays 1.5% (half-Kelly) — **it is not raised**; the
factors *reallocate within the band*.

| Factor | Formula | Bounds | Data need | Fail-safe (missing) |
|---|---|---|---|---|
| m_regime_edge | §7.3 | [0.5,1.5] | regime + matrix | 1.0 |
| m_opportunity | §13 map | [0.6,1.15] | opportunity score | 1.0 |
| m_confidence | `0.7 + 0.3·conf` | [0.7,1.0] | regime conf | 0.85 (mid) |
| m_transition | `1 − 0.4·transition_risk` | [0.6,1.0] | transition risk | 0.8 |
| m_drawdown | `1 − dd_from_peak/DD_BUDGET` clamped | [0.5,1.0] | equity peak | 1.0 (but §9.5 still binds) |
| m_correlation | §10.4 | [0.5,1.0] | rolling corr | 0.7 (cautious) |
| m_shadow, m_score | existing `risk.py`/`shadow` | [0.8,1.2] each | shadow buckets | 1.0 |

### 9.4 Portfolio open-risk budget (NEW — the missing aggregate)
Track, each cycle (new `PortfolioRiskBudgeter`):
```
open_stop_risk        = Σ_trades (remaining_notional · stop_dist_frac + rt_cost)   # true £-at-risk
corr_adj_open_risk    = sqrt( rᵀ Σ r )   # r = per-trade risk vector, Σ = corr matrix (§10)
regime_risk_budget    = equity · REGIME_RISK_BUDGET_PCT(regime)   # e.g. trend 8%, chop 4%, panic 2%
daily_loss_remaining  = max_daily_loss − today_realized_loss
daily_profit_remaining= effective_target − today_gain
```
A new entry is admitted only if `corr_adj_open_risk + new_trade_risk ≤
regime_risk_budget` **and** it does not push estimated worst-case cluster loss
past `daily_loss_remaining`. This is the portfolio-level gate the brief asks
for and is **engine-support** (applied in `apply_caps`), not in `decide()`.

### 9.5 Risk-of-ruin & drawdown budget (§K)
Offline (harness) + online monitor:
```
ruin_prob      ≈ ((1-edge)/(1+edge))^(equity/risk_per_trade)   # Kelly ruin approx, per config
dd95, dd99     = Monte-Carlo drawdown quantiles (existing walkforward MC)
max_streak     = expected losing streak from win%
cluster_stop_loss = worst-case simultaneous stop of an open correlated cluster
```
A risk increase (any regime tilt >1.0) is **only** permitted if: expected
compound growth rises, `ruin_prob ≤ RUIN_CEILING`, `dd99 ≤ DD_BUDGET`, OOS
supports it, and parameter sensitivity is low (§I). Encoded as an assertion in
the matrix-promotion pipeline, not a runtime toggle.

---

## 10. Correlation model

### 10.1 Replace the static cluster map
`allocation.CORRELATION_CLUSTERS` is a partial hand-map. New `correlation.py`
computes **rolling return correlation** across the working universe each cycle
(cached; 30×4h-bar window), producing a live `Σ` matrix and derived clusters.

### 10.2 Signals computed
- **Rolling pairwise corr** (30-bar returns) → live cluster assignment
  (threshold-linked, e.g. corr≥0.7 = same cluster).
- **Same-direction correlation:** for the *open book*, sum of correlated
  same-side exposure (the "6 longs = 1 big bet" detector).
- **BTC-beta / net directional exposure:** Σ(signed notional · beta_to_BTC).
- **Tail correlation:** correlation of the worst-decile joint moves (crash
  co-movement) — used to size the Panic budget.

### 10.3 Controls (turn the existing OFF caps ON, regime-tighten them)
- `MAX_PER_CLUSTER` — activate; regime-scaled (trend looser, panic = 1).
- `MAX_SAME_SIDE` — activate; cap net long/short count in high-corr regimes.
- `MAX_CLUSTER_EXPOSURE_PCT` — activate; cap cluster notional.
- **Net-directional cap:** new `MAX_NET_DIRECTIONAL_PCT` — |long−short| notional.

### 10.4 Correlation risk multiplier (sizing, not just gating)
```
m_correlation = clamp( 1 − CORR_PENALTY · same_side_cluster_load , 0.5, 1.0 )
same_side_cluster_load = correlated_same_side_notional / equity
```
So the 5th correlated long is sized down *and*, past the cap, rejected — the
portfolio treats a correlated cluster as one position, exactly as the brief
requires.

### 10.5 Guard rails
- Correlation uncomputable (thin data) → `m_correlation = 0.7` (cautious) and
  cluster caps fall back to the static map. **Fail-safe, never fail-open.**
- Correlation is advisory to *sizing/admission* only — it never changes
  `decide()`.

---

## 11. Position sizing formula (ordered pipeline)

The brief's required order, mapped to code (all inside the shared
`RiskManager.evaluate`, driven by the controller's `risk_multiplier`):
```
1. balance / equity                          (pf.balance)
2. risk budget      = equity · effective_risk_pct/100   (§9.3 multiplier chain)
3. stop distance    = normalize_stop(...)               (risk.py, unchanged)
4. cost estimate    = rt_cost_frac                      (taker+slippage ×2)
5. position notional= risk_budget / (stop_dist+rt_cost) (cost-inclusive, exists)
6. portfolio exposure check   → clip to exposure room   (exists)
7. correlation-adjusted risk check → §9.4 budget admit  (NEW, apply_caps)
8. available margin  = balance − open_margin            (exists)
9. liq-safe leverage → §12                              (risk._solve_leverage)
10. margin used      = notional / leverage              (exists)
11. final risk utilisation                              (exists, instrumented)
```
Steps 1–6, 8–11 already exist. **Only step 7** (portfolio correlation budget) is
new, and it is an *engine-support admission test* in `apply_caps`, keeping
`decide()`/`RiskManager` parity intact.

---

## 12. Leverage & margin formula

Keep the "leverage never creates risk; notional is sized first" invariant
(`risk.py` docstring). Improvements:

### 12.1 Binance maintenance-margin **tiers**
Replace the flat `MAINT_MARGIN_RATE=0.005` with a per-symbol tier lookup
(`symbol_filters.margin_rules_json` already exists in storage/schema —
`storage.py:231`). Large notional → higher MM tier → lower liq-safe leverage.
```
mm_rate(symbol, notional) = tier_lookup(margin_rules_json, notional)   # fallback flat 0.005
lev_ceiling = floor(1 / (LIQ_SAFETY_BUFFER·stop_dist_frac + mm_rate(sym,notional)))
```
Iterate once (notional depends on nothing that depends on leverage here, so a
single tier lookup at the sized notional is exact enough; assert stop-safe
after).

### 12.2 Funding in holding cost
For legs with multi-settlement holds (donchian/ichimoku run days), add expected
funding to the cost term used in sizing (already modelled in backtest via
`funding_cost`; surface it into the live sizing cost so paper matches). Small
but real for the swing legs.

### 12.3 Regime-aware margin reserve
`FREE_MARGIN_RESERVE_PCT` becomes `free_margin_reserve_pct(regime)`: higher in
Panic/Uncertain (e.g. 40%), lower in confirmed Strong Trend with low
correlation (e.g. 15%). Bounded [15,50]. This is the "use more capital when
genuinely diversified, hold reserve when everything correlates" behaviour.

### 12.4 Guard rails
- Tier lookup missing → fall back to the flat conservative 0.005 (never a
  *lower* MM than today).
- Isolated-margin approximation retained (the engine trades isolated); the
  liq-safety invariant `stop fires before est. liquidation` is re-asserted
  after any tier change (existing `stop_safe` check, `risk.py:254`).
- Regime reserve only ever *raises* reserve above today's 20% in stressed
  regimes; lowering below 20% requires `REGIME_MARGIN_RESERVE_ENABLED=true` +
  measured OOS support.

---

## 13. Dynamic slot / exposure rules & Daily Opportunity Score

### 13.1 Daily Opportunity Score (§A) — `portfolio.py`
```
opportunity = 100 * clamp01(
      w_r · regime_quality          # confidence·favourability of active legs' regimes
    + w_e · active_edge_strength    # Σ active-leg weights (from §7 matrix)
    + w_b · market_breadth
    + w_l · liquidity_quality
    + w_v · volatility_suitability  # inverted U — too low & too high both bad
    + w_s · signal_availability     # candidates detected recently
    − p_c · correlation_penalty
    − p_x · execution_cost_penalty  # spread/slippage stress
    − p_u · regime_uncertainty )
```
Bands (thresholds **calibrated from history**, not guessed):
| Score | Behaviour |
|---|---|
| 80–100 | high-quality day: full slots, budget toward ceiling, target toward ceiling |
| 50–80 | standard |
| 30–50 | reduced slots/exposure, tighter ranking, budget floor |
| <30 | capital preservation: minimal or no new entries |

### 13.2 Regime → slots / exposure (measured defaults)
| Regime | max_open (of 6) | exposure cap | notes |
|---|---|---|---|
| Strong Trend (low corr) | up to 6 | up to 300% | correlation cap enforced |
| Weak Trend | 4–5 | 200–250% | |
| Chop | 2–3 | 100–150% | tighter ranking; zero if no chop-edge leg |
| Vol Expansion | 4–5 | 200% | tighter spread/slippage |
| Panic | 1–2 | 50–100% | majors only, small notional, high reserve |
| Uncertain | 1–2 | ≤100% | strongest legs only |
**These are seed defaults; §17 backtest tunes them and §I checks the plateau.**

### 13.3 Incremental Trade Value (§B) & slot replacement (§C)
Admission (in `apply_caps`, when slots contended):
```
IncrementalValue = E[net_return]
    − fees_slippage − correlation_cost − tail_risk_contribution
    − margin_opportunity_cost − portfolio_dd_contribution
admit new entry  iff  IncrementalValue > 0  AND  IncrementalValue > weakest_open_marginal
```
**Slot replacement is conservative and off by default** (`SLOT_REPLACE_ENABLED`):
never break a *validated exit*. Replacement only ever means "prefer the stronger
new signal for the *next free* slot"; it does **not** force-close a healthy open
trade to make room unless the open trade is already past a defined weakness
condition (e.g. time-stop-imminent + negative unrealized + regime turned against
its leg). Ship the admission test first; ship forced replacement only after
paper evidence.

---

## 14. Daily target & profit protection

### 14.1 Reframe the daily "%": it is protection, not a quota
Answer to the brief's questions, from the data: a Sharpe-1.35 book does **not**
produce a fixed daily %. The daily figure is a **profit-lock**, not a target to
manufacture. Keep the existing `_daily_profit_target_guard` flatten but make the
*level* fully regime/opportunity-conditioned and add soft/hard tiers.

### 14.2 The measured questions (answer in the harness before changing behaviour)
`scripts/daily_target_optimize.py` (exists) + a new regime split must report:
daily-return distribution, median daily R, %-of-days ≥4%, R needed to hit 4% at
current size/frequency, feasibility per regime, and whether flatten cuts
long-run edge (does closing winners early for the daily bank reduce total R?).
**If flatten is shown to cut edge, the default level rises or flatten becomes
trend-only.**

### 14.3 The structure (replaces a single flat target)
```
soft_target(regime, opportunity)  → start scaling out / tighten trailing
hard_profit_lock(regime)          → flatten + lock (existing mechanism)
equity_trailing_lock              → protect a % of peak equity (giveback guard, exists)
drawdown_from_peak_protection     → §9.3 m_drawdown throttle
low-opportunity day: target ↓, risk ↓, trades ↓
strong-trend day:    target ↑, let winners run (existing adaptive ceiling)
uncertain day:       capital preservation
```
Reuse: `daily_profit_flatten`, `daily_profit_adaptive`, `daily_giveback_guard`
all exist. New: make the *target level* a function of (regime, opportunity), and
add the soft-target scale-out tier.

### 14.4 Guard rail
Profit protection must **not** contradict a validated strategy exit for a
*single* trade in isolation — the flatten is a *portfolio* action (bank the
day), applied to all at once, and is already parity-safe via
`executor.force_close`. Do not add per-trade early exits that would break the
measured exit shapes (`SYSTEM_STATE §6` — earlier exits all destroyed yield).

---

## 15. Regime transition logic

### 15.1 On confirmed regime change (hysteresis-gated, §6.3)
1. **New entries** immediately adopt the new regime's allocation (weights,
   universe, slots, budget). Automatic — the controller reads effective label.
2. **Open trades are NOT blindly closed.** Instead re-evaluate:
   - recompute exit urgency (tighten trailing if the new regime is adverse to
     that leg per §7 matrix),
   - stop *new* entries from legs that are `shadow-only`/`passive` in the new
     regime (old-regime strategies stop adding),
   - raise the portfolio drawdown throttle if `transition_risk` is high.
3. **High transition risk** (even without a label flip) → pre-emptively reduce
   risk budget and slots.
4. **Panic override** → immediate (skip confirmation), tighten everything.

### 15.2 Whipsaw vs lag balance (must be tested, §17)
Hysteresis params (`REGIME_CONFIRM_BARS`, Schmitt thresholds, `CONF_PERSIST_BARS`)
are swept on the regime-misclassification stress test: too tight = whipsaw churn,
too loose = late reaction to real breaks. Choose the plateau, not the point
optimum (§I).

### 15.3 Guard rail
Transition-driven *changes to open trades* are limited to exit-urgency and
sizing of *future* adds. No transition rule may force a market close of a
healthy trade except the existing portfolio-level daily flatten/giveback.

---

## 16. Shadow integration & counterfactual engine

### 16.1 Role in the new architecture
Shadow stays **observe-first, never a veto** (`CLAUDE.md` #4). New uses:
- monitor the regime model (log every `RegimeState` + realized forward returns),
- measure strategy×regime and coin×regime edge (feeds §7 matrix refresh),
- calibrate the risk multipliers (does `m_regime` predict realized R?),
- track hypothetical performance of `passive`/`shadow-only` legs per regime,
- regime-misclassification analysis (label vs realized).

### 16.2 Counterfactual policy engine (§G) — extend `shadow_ab`
`shadow_ab` already records `risk_multiplier_would_be` / `score_delta_would_be`
per resolved signal. Generalise to a small set of **named policy variants**
evaluated per decision without touching the live position:
- risk +/− one band, one extra slot, no-regime-filter, alt strategy weight,
  no-profit-flatten, alt leverage policy, alt universe.
Store `(policy_version, variant, would_be_outcome_R)`; the drift/attribution
layer compares live vs counterfactual to justify promotions with **live**
comparative evidence, not just backtest.

### 16.3 Promotion discipline (unchanged philosophy)
`observe → recommend → paper-validate → owner-approve → promote`. No parameter
reacts to a handful of trades; minimum sample + Bayesian shrinkage + confidence
intervals (existing shadow-readiness staircase, `SYSTEM_STATE §11`). The live
system never self-optimises unattended (no Optuna auto-apply).

---

## 17. Backtest methodology

### 17.1 Staged validation (each stage vs the current baseline)
1. Baseline (current deployed book) — reference numbers.
2. Regime ensemble **observational only** (compute + store, change nothing).
3. Regime-based strategy enable/disable (§7).
4. Regime-based risk allocation (§9.3).
5. Regime-based coin universe (§8).
6. Regime-based slots/exposure (§13).
7. Correlation-aware sizing/admission (§10).
8. Margin/leverage upgrades (§12).
9. Full system combined.
**No stage advances to the live decision path until it beats baseline on §18.**

### 17.2 Validation techniques (reuse existing harness stack)
`walkforward.py` (segmented OOS, MC drawdown, deflated Sharpe, plateau),
`portfolio_frontier.py`, `leg_review.py`, `regime_tilt_validate.py`,
`holdout_check.py` already provide: IS/OOS, walk-forward, purged CV,
symbol-holdout, Monte-Carlo, parameter perturbation, fee/slippage sensitivity,
delayed-fill, and DSR multiple-testing deflation. Add:
**regime-balanced test** (equal weight per regime so a rare regime can't be
ignored), **regime-misclassification stress** (corrupt N% of labels, measure
degradation), **correlation-shock / flash-crash / long-losing-streak /
exchange-downtime** scenario replays.

### 17.3 Metrics (per regime, per leg, per coin)
Net expectancy, daily & per-trade Sharpe, Sortino, PF, CAGR, MaxDD, CVaR,
recovery factor, Ulcer index, win%, avg/median R, trade freq, capital/margin/risk
utilisation, exposure, turnover, total fee drag. **Return decomposition (§J):**
```
Total = StrategyEdge + RegimeAllocationEffect + CoinSelectionEffect
      + RiskWeightingEffect + TimingEffect − Fees − Slippage − Funding
      − CorrelationLoss − ProfitLockOpportunityCost
```
If higher return is only more risk taken, it is **not** reported as edge
improvement.

---

## 18. Acceptance criteria

A stage/phase is accepted only if **all** hold vs baseline:
- [ ] Net post-cost expectancy ≥ baseline (not worse in aggregate).
- [ ] Daily Sharpe reliably ≥ baseline (bootstrap CI lower bound > baseline).
- [ ] MaxDD and CVaR **not materially worse** (drawdown budget respected).
- [ ] Positive in **every** regime slice it claims to trade (no "great in trend,
      collapses in chop" — that leg becomes passive/shadow there instead).
- [ ] Robust to parameter perturbation (plateau, §I) — not a knife-edge optimum.
- [ ] Not overfit to the recent slice (2025+ slice holds up).
- [ ] Survives regime-misclassification stress (bounded degradation, still ≥
      baseline under X% mislabelling).
- [ ] Edge survives a fee/slippage bump (cost-sensitivity check).
- [ ] Return decomposition shows the gain comes from allocation/selection, not
      from covertly higher risk.
Rejection on **any** → the change stays observational or is dropped.

---

## 19. File-by-file implementation plan

> Convention for every item: **file · target class/fn · new class/fn · input ·
> output · formula · guard rail · test · acceptance.** New behaviour is
> flag-gated default-OFF; `decide()` is never modified.

### 19.1 `src/aurvex/regime.py` (NEW)
- **New:** `RegimeEnsemble`, `RegimeState`, `RegimeProvider` (interface),
  `EngineRegimeProvider` (wraps `Engine.provider`), `HistoricalRegimeProvider`
  (feeds bars in backtest).
- **Input:** market data provider + universe bars (closed only). **Output:**
  `RegimeState` (§5.4).
- **Formula:** §5–§6.
- **Guard rail:** `data_ok=False` on anchor loss → engine fail-safe; closed
  bars only; cached per `REGIME_REFRESH_SEC`.
- **Test:** `tests/test_regime_ensemble.py` — deterministic synthetic series
  produce expected labels; hysteresis blocks single-bar flips; missing dim
  lowers confidence; panic overrides confirmation.
- **Acceptance:** reproduces the current 1-D trend score exactly when only the
  trend dim is enabled (backward-compatible superset).

### 19.2 `src/aurvex/correlation.py` (NEW)
- **New:** `CorrelationController` — rolling Σ, live clusters, same-side load,
  net-directional exposure, tail corr.
- **Input:** universe return series + open book. **Output:** cluster map,
  `m_correlation`, admission verdict.
- **Guard rail:** thin data → static-map fallback + cautious multiplier;
  advisory to sizing/admission only.
- **Test:** `tests/test_correlation_controller.py` — 5 correlated longs collapse
  to one cluster; cap rejects the 6th; uncomputable → fallback.

### 19.3 `src/aurvex/portfolio.py` (NEW — the central controller)
- **New:** `PortfolioController.plan(regime, pf, candidates) -> PortfolioPlan`
  with `DailyOpportunityScore`, `StrategyRegimeAllocator`, `DynamicUniverse`,
  `PortfolioRiskBudgeter`, `SlotExposurePlan`, `IncrementalValue`.
- **Input:** `RegimeState`, `PortfolioView`, ranked candidates, §7 matrix.
- **Output:** `PortfolioPlan {risk_multiplier_by_setup, active/passive/shadow
  legs, eligible_universe, max_open_this_cycle, exposure_cap_this_cycle,
  cluster_caps, opportunity_score, risk_budget, policy_version}`.
- **Guard rail:** every output has a baseline fallback; plan computed once/cycle;
  **never** calls `decide()`.
- **Test:** `tests/test_portfolio_controller.py` — each regime yields the
  documented slot/exposure/budget; low opportunity → fewer slots; disabled flag
  → byte-identical to baseline plan.
- **Acceptance:** with all new flags OFF, `plan()` returns today's static
  settings (parity preserved).

### 19.4 `src/aurvex/regime_matrix.py` (NEW) + `scripts/regime_matrix.py` (NEW)
- **New:** loader for `data/regime_matrix.json`; `edge_weight(leg, regime,
  confidence)` with Bayesian shrinkage (§7.3).
- **Guard rail:** unknown (leg,regime) → global prior; thin cell → shrink.
- **Test:** `tests/test_regime_matrix.py` — shrinkage pulls thin cells toward
  prior; confidence scaling toward 1.0.

### 19.5 `src/aurvex/drift.py` (NEW)
- **New:** `DriftMonitor` — per (leg × regime) compares realized vs expected
  expectancy/win%/avgR/slippage/holding; state machine `ACTIVE → REDUCED_RISK →
  SHADOW_ONLY → REVIEW`.
- **Guard rail:** advisory (recommends state); only owner-approved flags flip
  live; never auto-promotes to live.
- **Test:** `tests/test_drift_monitor.py` — injected decay walks the state
  machine; recovery walks it back.

### 19.6 `src/aurvex/engine.py` (MODIFY — wiring only)
- **Modify:** `_market_regime` → delegate to `RegimeEnsemble` (keep the old
  `{score,adx}` shape as a compatibility view so existing callers/tests hold).
  In `_cycle`, after `cycle_buckets`, compute `regime = self.regime.evaluate()`
  and `plan = self.portfolio.plan(...)`; feed `plan` into `_risk_modulation`
  (extra factors), `rank_signal`, `apply_caps` (dynamic caps + correlation +
  incremental value), and the scanner working set. `_effective_profit_pct` reads
  the plan's target. Add transition handling in `_manage_open_trades`.
- **Guard rail:** all new inputs behind flags; when OFF, the existing code paths
  run unchanged. `decide()` untouched.
- **Test:** `tests/test_engine_regime_wiring.py` + all existing engine tests
  stay green.
- **Acceptance:** flags OFF → cycle behaviour byte-identical (existing suite).

### 19.7 `src/aurvex/risk.py` (MODIFY)
- **Modify:** `_solve_leverage` → MM-tier lookup (§12.1); add funding to cost
  term (§12.2); regime margin reserve (§12.3) via a passed-in reserve override.
- **Guard rail:** tier missing → flat 0.005; liq-safety re-asserted; reserve
  only rises in stress unless flag+evidence.
- **Test:** extend `tests/test_leverage_margin.py`, `test_efficient_leverage.py`
  — large notional → lower leverage; funding raises cost; reserve regime-scales.
- **Acceptance:** with tier/funding/reserve flags OFF, identical sizing to today.

### 19.8 `src/aurvex/allocation.py` (MODIFY)
- **Modify:** `apply_caps` accepts dynamic caps + correlation controller +
  incremental-value test; `rank_signal` accepts a regime/edge tilt term.
- **Guard rail:** defaults reproduce current behaviour (caps 0 = off).
- **Test:** extend `tests/test_global_ranking_T5.py`, `test_edge_ranking.py`.

### 19.9 `src/aurvex/shadow.py` (MODIFY)
- **Modify:** log `RegimeState` per tracked signal; extend `shadow_ab` to named
  policy variants (§16.2).
- **Test:** `tests/test_counterfactual_policies.py`.

### 19.10 `src/aurvex/config.py` (MODIFY) — see §21. `src/aurvex/edge_analysis.py`
(MODIFY) — add return decomposition (§J). `scripts/` — new `regime_matrix.py`,
`regime_backtest.py` (staged §17 runner), extend `daily_target_optimize.py`.

---

## 20. Database schema changes

All additive, via `Storage._migrate` (the established `ALTER TABLE …
IF NOT EXISTS`-style pattern, `storage.py:315`). No table rewrites.

1. **`trades`** — add columns (policy audit trail, §H):
   `policy_version TEXT DEFAULT ''`, `regime_label TEXT DEFAULT ''`,
   `regime_confidence REAL DEFAULT 0`, `opportunity_score REAL DEFAULT 0`,
   `m_regime REAL DEFAULT 1`, `m_opportunity REAL DEFAULT 1`,
   `m_correlation REAL DEFAULT 1`, `m_confidence REAL DEFAULT 1`,
   `m_transition REAL DEFAULT 1`, `cluster TEXT DEFAULT ''`,
   `accept_reason TEXT DEFAULT ''`.
2. **`signal_events`** — already stores `metadata` JSON; stamp the same regime/
   plan fields there (no schema change; extend the dict).
3. **NEW `regime_history`** — `(ts, label, confidence, prev_label,
   transition_risk, sub_scores_json, opportunity_score, data_ok)`; one row per
   regime recompute. Index on `ts`.
4. **NEW `policy_versions`** — `(version TEXT PRIMARY KEY, created_ts, regime_model,
   risk_allocator, universe_policy, margin_solver, config_snapshot_json)`.
5. **`shadow_ab`** — add `policy_variant TEXT DEFAULT 'legacy'` (named
   counterfactuals, §16.2).
6. **NEW `regime_leg_stats`** (drift, §14/§5) — rolling realized stats per
   (leg × regime): `(leg, regime, n, exp_r, win, avg_r, updated_ts)`.

Guard rail: every migration is idempotent and NULL/default-tolerant (metrics
already tolerate NULL PnL rows — `metrics.py:27`).

---

## 21. Config / env additions

All in `config.py` with **measured defaults and default-OFF flags**. Add a
matching block to `.env.example` and to `scripts/apply_fast_paper_env.py`
(disarmed). Grouped:

```
# --- Regime ensemble (observation first) ---
REGIME_ENSEMBLE_ENABLED=false        # master switch; false → legacy 1-D trend
REGIME_DIMS=trend,vol,breadth,corr,liq
REGIME_CONFIRM_BARS=2                 # hysteresis persistence
REGIME_CONF_MIN=0.35                  # below → UNCERTAIN
REGIME_CONF_PERSIST_BARS=3
REGIME_PANIC_IMMEDIATE=true
REGIME_TREND_ENTER=0.66 REGIME_TREND_EXIT=0.55   # Schmitt thresholds
REGIME_VOL_LOOKBACK=180              # ATR/BB percentile window (bars)
REGIME_CORR_WINDOW=30
# --- Strategy×regime matrix ---
REGIME_MATRIX_ENABLED=false
REGIME_MATRIX_PATH=data/regime_matrix.json
REGIME_MATRIX_MIN_N=150              # shrinkage threshold
# --- Opportunity / slots / exposure ---
OPPORTUNITY_SCORE_ENABLED=false
REGIME_DYNAMIC_SLOTS_ENABLED=false
REGIME_DYNAMIC_EXPOSURE_ENABLED=false
REGIME_SLOTS_JSON={...per-regime max_open...}     # measured defaults
REGIME_EXPOSURE_JSON={...per-regime exposure %...}
# --- Universe ---
REGIME_DYNAMIC_UNIVERSE_ENABLED=false
UNIVERSE_MIN_SAMPLE=30
# --- Correlation controller ---
CORRELATION_CONTROLLER_ENABLED=false
CORR_CLUSTER_THRESHOLD=0.70
CORR_PENALTY=0.5
MAX_NET_DIRECTIONAL_PCT=0            # 0=off
# (existing: MAX_PER_CLUSTER, MAX_SAME_SIDE, MAX_CLUSTER_EXPOSURE_PCT — activate)
# --- Portfolio risk budget ---
PORTFOLIO_RISK_BUDGET_ENABLED=false
REGIME_RISK_BUDGET_JSON={...per-regime budget %...}
DD_BUDGET_PCT=15
RUIN_CEILING=0.02
# --- Transition management ---
REGIME_TRANSITION_MGMT_ENABLED=false
TRANSITION_RISK_K=0.4
# --- Leverage / margin upgrades ---
MM_TIERS_ENABLED=false
FUNDING_IN_SIZING_ENABLED=false
REGIME_MARGIN_RESERVE_ENABLED=false
# --- Daily target ---
DAILY_TARGET_REGIME_ENABLED=false   # (extends existing adaptive target)
SOFT_TARGET_ENABLED=false
# --- Counterfactual / drift / policy ---
COUNTERFACTUAL_POLICIES_ENABLED=false
DRIFT_MONITOR_ENABLED=false
POLICY_VERSION=RAPB-v0               # stamped on trades
```
Rule: **an explicit env var always overrides its profile default** (existing
convention). The five-gate live lock and `RISK_PCT` band are untouched. Do not
add a flag that defaults a gate on.

---

## 22. Dashboard changes (`src/aurvex/dashboard/app.py`)

Add a **Regime & Allocation** panel (read-only JSON route + HTML section):
current regime + confidence + duration + transition risk + sub-dimension labels;
active/passive/shadow legs + weights; active coin universe + why coins were
dropped; risk-multiplier breakdown (base → effective, each factor); portfolio
open risk + correlation-adjusted risk + exposure + margin used/free + avg
leverage; slot usage; daily opportunity score + target + profit-lock state;
per-decision accept/reject reason (why accepted, why risk ↑/↓, why universe
changed); regime history timeline; performance-by-regime table; return
decomposition. All read-only (dashboard never writes — `ARCHITECTURE.md`).

Test: `tests/test_dashboard_regime_panel.py` (route returns the fields; renders
with empty/None gracefully).

---

## 23. Telegram changes (`src/aurvex/telegram.py`)

Short, explanatory messages (respect quiet hours, existing infra):
- **Regime change** (only on *confirmed* change, hysteresis-gated — avoid spam):
```
🧠 REGIME CHANGE  CHOP → STRONG TREND
Confidence 82% · transition risk 18%
Active: ichimoku, squeeze@4h, donchian
Risk: 1.5% base → 1.82% effective
Slots: 3 → 6 · Universe: 8 → 14 qualified
Reason: ADX expansion + breadth + vol breakout
```
- **Opportunity/day summary**, **drift alert** (leg → REDUCED/SHADOW),
  **correlation-shock warning**, **fail-safe engaged** (regime data lost →
  baseline).
Test: `tests/test_telegram_regime_events.py` (format + dedup + quiet-hours).

---

## 24. Test files to add

`test_regime_ensemble.py`, `test_correlation_controller.py`,
`test_portfolio_controller.py`, `test_regime_matrix.py`, `test_drift_monitor.py`,
`test_engine_regime_wiring.py`, `test_counterfactual_policies.py`,
`test_dashboard_regime_panel.py`, `test_telegram_regime_events.py`,
`test_regime_parity.py` (**critical:** all new flags OFF ⇒ `decide()` output and
trade sizing byte-identical to baseline across paper/live), plus extensions to
`test_leverage_margin.py`, `test_efficient_leverage.py`, `test_global_ranking_T5.py`,
`test_edge_ranking.py`, `test_daily_profit_flatten.py`, `test_regime_edge_weight.py`.
The existing 778-test floor must stay green at every step.

---

## 25. Migration plan

1. **Additive DB migrations** ship first (idempotent, NULL-tolerant); no
   behaviour change.
2. **New modules ship dark** (imported, flag-gated OFF) — the parity test
   (`test_regime_parity.py`) proves zero behaviour change.
3. **Observational phase** (§26 Phase 1): regime + opportunity computed and
   stored/displayed; `decide()`/sizing untouched.
4. **Progressive wiring** one lever per phase, each behind its own flag, each
   with a backtest gate (§17/§18) before the flag is allowed on in paper.
5. **`scripts/apply_fast_paper_env.py`** gains the new block (all disarmed) and
   keeps the current line as rollback reference (established pattern).
6. **`SYSTEM_STATE.md`** updated at each phase (it is the source of truth).

---

## 26. Phased implementation (the build order)

| Phase | Scope | Ships changing decisions? | Gate to next |
|---|---|---|---|
| **1** | Regime ensemble + opportunity score, **observational** (store/display) | No | Ensemble reproduces baseline; labels sane on 6y replay |
| **2** | Strategy×regime + coin×regime **measurement** (harness → `regime_matrix.json`) | No | Matrix filled, DSR-clean, per-regime slices reported |
| **3** | Dynamic **risk allocation** (regime+matrix multiplier, confidence, transition) | Yes (flag) | §18 vs baseline; OOS + regime-balanced pass |
| **4** | **Correlation-aware** slots/exposure/admission | Yes (flag) | §18; correlation-shock stress pass |
| **5** | **Leverage/margin** solver upgrades (tiers, funding, regime reserve) | Yes (flag) | §18; liq-safety invariant holds; efficiency ↑, risk flat |
| **6** | **Counterfactual** policy engine + **drift** monitor | No (advisory) | Counterfactuals recorded; drift state machine validated |
| **7** | **Dashboard / Telegram / policy audit trail** | No | Panels render; policy_version stamped |
| **8** | **Long paper validation** + controlled promotion | Yes, owner-gated | 30–50 trades/leg at expectancy consistent with validated; owner decision |

**Each phase is measured against baseline independently. A phase does not wire
into the live decision path until it passes its acceptance gate.** Phases 1, 2,
6, 7 are observational/analytical and can proceed in parallel with paper running.

---

## 27. Paper validation plan

- Run baseline and the phase-N build side-by-side where possible (the
  counterfactual engine, §16, gives *live* A/B without a second account).
- Minimum **30–50 resolved trades per leg per active regime** before judging a
  regime cell (mirrors `SYSTEM_STATE §8`). No parameter reacts to a handful of
  trades.
- Watch: per-regime expectancy vs the matrix prediction (calibration), drift
  states, correlation-adjusted open risk vs budget, fail-safe engagements, and
  the return decomposition (is gain from allocation or from more risk?).
- A phase's paper result must **confirm** its backtest, not merely "not
  contradict" it, before the next decision-changing phase arms.

---

## 28. Live promotion gates (unchanged five-gate lock + new pre-conditions)

Live stays OFF behind the existing five-gate lock (`CLAUDE.md` #1). This project
adds **no** new path to the exchange and weakens **no** gate. Before any live
consideration, in addition to the existing requirements (`SYSTEM_STATE §5`,
`LIVE_READY_CHECKLIST.md`):
- The regime-adaptive book must show, in **paper**, expectancy consistent with
  the validated numbers across ≥ the required trade count, in ≥2 distinct
  regimes.
- Drift monitor green (no leg in REVIEW), fail-safe never mis-fired, correlation
  budget respected.
- Owner explicit decision, trade-only key, canary sizing, clean reconcile.
- `test_regime_parity.py` green (the regime layer cannot alter the shared brain).

---

## 29. Risks & failure modes

| Risk | Mitigation |
|---|---|
| Regime model overfit / noisy labels | Observe-first phasing, hysteresis, confidence gating, plateau selection, regime-misclassification stress test |
| Thin per-regime cells → bad weights | Bayesian shrinkage to global prior; `REGIME_MATRIX_MIN_N` |
| Whipsaw churn on regime flips | Schmitt thresholds + `REGIME_CONFIRM_BARS` + cost of churn measured |
| Late reaction to real breaks | Panic immediate-override; transition-risk pre-emptive de-risk |
| Correlation matrix instability | Rolling window + static-map fallback + cautious multiplier on thin data |
| Diluting the coin-specific edge | Universe can only narrow within the validated set; never expands |
| Covert risk creep (higher return = more risk) | Return decomposition gate (§J); Kelly/ruin ceiling; `RISK_PCT` unchanged |
| Complexity regression / bug in the hot path | `decide()` untouched; parity test; per-phase flags; 778-test floor |
| Regime data feed loss | `data_ok=False` → hard fail-safe to baseline profile, block new entries (§16-guard) |
| Reintroducing forbidden complexity | No ML/multi-AI/Optuna hard gates; ensemble is transparent and disableable (`CLAUDE.md` #5) |
| Scalp temptation | Closed by evidence; this plan explicitly does not add scalp modes |

**Fail-safe principle (§17 of the brief):** on regime data missing/stale, low
confidence, uncomputable correlation, balance/reconcile mismatch, negative risk
budget, liq-safety unmet, illiquid/abnormal-spread coin, unstable transition, or
active kill switch → **do not open new trades** and **fall back to the current
validated baseline profile**. Fail-safe, never fail-open.

---

## 30. Final recommended configuration

**Answering the brief's 14 final questions directly:**

1. **Feasible?** Yes; ~40% exists, the rest is a bounded additive controller.
2. **How much already exists?** 1-D regime, regime×edge multiplier, adaptive
   profit target, ranking allocator with (dormant) correlation caps, cost-aware
   risk + efficient leverage, observe-first shadow with a counterfactual A/B
   table, full observability spine.
3. **The real missing architecture?** A *central controller* turning a
   *multi-dimensional, confidence-scored, hysteresis-stable* regime read into a
   *coherent joint* setting of risk budget / slots / exposure / universe /
   correlation caps / profit protection — plus the *measured* strategy×regime
   matrix, portfolio-level correlation-adjusted risk budget, drift detection,
   and policy audit trail.
4. **Real scalp or regime-multi-edge?** Regime-multi-edge, decisively. Scalp is
   structurally dead; more trades come from more independent edges allocated by
   regime.
5. **New data genuinely needed?** Only what the engine already fetches
   (universe OHLCV for breadth/correlation, ATR/BB for volatility, order book
   for liquidity) + Binance MM-margin tiers (already in `symbol_filters`).
6. **Data NOT needed?** Funding/OI/basis/liquidation feeds as *entry* signals
   (dead after cost); add as regime *context* only if a later phase proves OOS
   lift.
7. **What becomes dynamic?** Strategy weights, coin eligibility (within the
   validated set), per-trade risk multiplier, portfolio risk budget, max open,
   exposure cap, correlation caps, margin reserve, daily target/lock, trade
   admission — all regime-conditioned within measured bands.
8. **What stays fixed?** Base `RISK_PCT` 1.5% (half-Kelly), validated entry
   rules, the validated coin superset, `MAX_LEVERAGE` ceiling, liq-safety
   invariant, the five-gate live lock, and `decide()`.
9. **Where the upside comes from?** Regime-weighted allocation (+0.95 R/day
   measured) + edge-weighting toward high-Sharpe legs + drift-correction —
   *not* bigger bets or more coins.
10. **Biggest risk?** Overfitting the regime model / reacting to noise —
    mitigated by observe-first, hysteresis, confidence, shrinkage, plateau
    selection, fail-safe.
11. **Phases?** The eight phases in §26.
12. **What Claude Code does first?** **Phase 1 only:** build `regime.py`
    (multi-dim ensemble + `RegimeState` with confidence/hysteresis, reproducing
    the current 1-D trend exactly when only the trend dim is on) and the
    observational opportunity score; wire them to *store and display* only;
    ship the additive DB migrations and `test_regime_parity.py` proving zero
    behaviour change. **Change no decisions.**
13. **What blocks the next phase?** Each phase's §18 acceptance gate vs baseline
    (backtest) then paper confirmation; no decision-changing phase arms until its
    gate passes.
14. **How the final system runs?** The §4/§21 pipeline: every cycle it reads a
    confidence-scored multi-dimensional regime, scores the day's opportunity,
    selects/weights the legs and coins that are *measured*-positive in that
    regime, sizes each trade within the half-Kelly band by the composed
    multiplier, caps correlated/clustered risk at the portfolio level, allocates
    margin efficiently with liq-safety, protects profit and drawdown by regime,
    and continuously measures itself (counterfactual + drift + decomposition) —
    trading only when a genuine positive edge exists, never forcing a daily
    quota, never using leverage to manufacture risk, and always failing safe to
    the validated baseline.

**Recommended starting `.env` posture:** every new flag in §21 **OFF**; keep the
current deployed line (`SYSTEM_STATE §6`). Turn flags on **one phase at a time,
only after that phase passes its acceptance gate**, via
`scripts/apply_fast_paper_env.py` + owner restart. The live gates stay closed
throughout.

---

*End of REGIME_ADAPTIVE_PORTFOLIO_IMPLEMENTATION.md — hand this to Claude Code
and begin at Phase 1 (§26 / §30 Q12). Do not skip the observational phase.*
