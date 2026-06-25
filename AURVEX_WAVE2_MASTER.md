# AURVEX Wave 3 — Integrity First: Master Record

This document is the single source of truth for Wave 3 decisions, measurements, and outcomes.
Each block appends its results before a PR is opened. Numbers are falsifiable: every claim
traces back to a commit, a test assertion, or a dashboard snapshot.

---

## Wave 2 Frozen Baseline

**Frozen commit:** `4298795`
**Tag:** `wave2-baseline-4298795`
**Date frozen:** 2026-06-23
**Mode:** paper (live permanently OFF)

### Effective config at freeze

| Key | Value |
|---|---|
| `AX_MODE` | `paper` |
| `LIVE_ENABLED` | `false` |
| `RISK_PCT` | `0.5` |
| `MAX_OPEN_TRADES` | `4` |
| `MAX_PORTFOLIO_EXPOSURE_PCT` | `200` |
| `MAX_LEVERAGE` | `10` |
| `FREE_MARGIN_RESERVE_PCT` | `20` |
| `LIQ_SAFETY_BUFFER` | `2.0` |
| `MAINT_MARGIN_RATE` | `0.005` |
| `TAKER_FEE_PCT` | `0.045` |
| `SLIPPAGE_ASSUMPTION_PCT` | `0.02` |
| `TRADE_THRESHOLD` | `60` |
| `WATCHLIST_THRESHOLD` | `50` |
| `SHADOW_APPLY` | `false` |
| `DATA_PROVIDER` | `ccxt` |

### Measured capital-efficiency facts (verbatim — falsifiable)

| Metric | Measured value | Target / budget |
|---|---|---|
| Realized risk per trade | **~0.21% of equity** | 0.5% (budget) |
| Risk utilisation | **~42% of budget** | 100% |
| Open notional / equity | **~199.8%** (exposure cap binding) | 200% cap |
| Blended leverage | **~2.6×** (not 10×; design, not limit) |  |
| MSTR example trade | **0.035% risk** (exposure room exhausted → clipped) | 0.5% |

**Root causes (documented for Block C):**

1. `risk._solve_leverage` picks the *smallest* leverage that fits notional into the
   slot-aware margin target. `MAX_LEVERAGE=10` is never the binding constraint; the
   binding constraint is `MAX_PORTFOLIO_EXPOSURE_PCT=200` + first-come slot ordering.
2. Exposure-cap clipping reduces notional → reduces `max_loss` → realized risk << 0.5%.
3. First-come scan order fills slots with earlier-scanned (not highest-rank) signals.
   Score 73 candidates rejected while lower-score incumbents hold slots.
4. Shadow learner: observe-only (advisory only, not wired into sizing). Score
   anti-predictivity hypothesis unconfirmed — T4 measures this.

### Paper trading snapshot (N=34 trades at freeze)

| Metric | Value |
|---|---|
| Net PnL | see dashboard |
| Win% | see dashboard |
| Profit Factor | see dashboard |
| Expectancy (R) | see dashboard |
| Max DD | see dashboard |
| Shadow resolved | ~34 (current epoch) |
| Shadow legacy rows | ~15 497 (pre-epoch, not comparable) |

*Note: specific PnL/win% numbers are live dashboard reads — record them manually
when freezing a live server. The structural facts above are code-derived and exact.*

### Test baseline

- **145 tests green** at commit `4298795`
- All Wave 1 invariants hold: reconciliation, -1.0R full stop, liq safety, no lookahead

---

## Block A — Instrumentation (W3-T0, T1, T1b)

Branch: `claude/wave3-integrity-first-nv0f9k`

### W3-T0 status
- [x] Baseline tag `wave2-baseline-4298795` created and pushed
- [x] This document committed with frozen baseline section
- [x] Zero code change

### W3-T1 status
- [x] `RiskResult` extended with 5 observational fields: `target_notional`, `target_risk_amount`, `actual_risk_amount`, `risk_utilisation_pct`, `clip_reason`
- [x] `clip_reason` values: `none` (uncapped) | `exposure_cap` | `min_notional` | `margin_cap`
- [x] Fields populated in `RiskManager.evaluate` at the exact clip branch; no sizing change
- [x] `Decision.metadata` carries all 4 key fields for REJECTED signals too
- [x] `Trade.metadata` carries fields at open via `executors.build_trade`
- [x] Storage: 4 dedicated columns added (`target_risk_amount`, `actual_risk_amount`, `risk_utilisation_pct`, `clip_reason`) + `_migrate()` backfill (`clip_reason='legacy'` on pre-T1 rows)
- [x] `_trade_to_row` / `_row_to_trade` / `upsert_trade` updated (29 cols)
- [x] Tests: `tests/test_risk_instrumentation.py` (9 tests) + `tests/test_no_behavior_change_T1.py` (10 tests) — all green
- [x] Golden test: parameterized over 7 cases confirms `position_size`, `leverage`, `max_loss` byte-identical to pre-T1 algorithm

### W3-T1b status
- [x] `telegram.trade_opened` updated: accepts `balance` kwarg; shows 6 labelled numbers in compact block: stop dist, acct risk, margin roe at stop, notional, leverage, liq distance
- [x] `dashboard._trade_dict`: accepts `balance` kwarg; returns `price_move_to_stop_pct`, `account_risk_pct`, `margin_roe_at_stop_pct`, `liq_distance_pct` alongside existing `position_size`/`leverage`
- [x] `portfolio_metrics` endpoint: adds `exposure_pct`, `portfolio_risk_util_pct`, `open_clip_breakdown`, `session_clip_breakdown`
- [x] Tests: `tests/test_leverage_concepts_T1b.py` (7 tests) — all green

### Gate A status
- [x] **171 tests green** (145 original + 26 new)
- [x] Zero behavior delta: golden test proves `(decision, position_size, leverage, max_loss)` unchanged
- [x] Baseline frozen at tag `wave2-baseline-4298795`
- [x] `AURVEX_WAVE2_MASTER.md` updated with first instrumented snapshot
- [x] Live stays OFF (`LIVE_ENABLED=false`, no executor changes)

---

## Block B — Cohorts + Shadow integrity (minimal)

Branch: `w3-blockB-cohorts`

### W3-T2 — Shadow cohort ayrımı (minimal)
- [x] `shadows` tablosuna `epoch TEXT DEFAULT 'legacy'` kolonu eklendi
- [x] `_migrate()`: mevcut satırlar `ts >= epoch['started_ms']` ise current epoch label'ı, aksi 'legacy'
- [x] `track_signal`: yeni satırlar `epoch = current_epoch` ile tag'lenir
- [x] `stats(epoch=...)`: epoch filtresi + default = current epoch (legacy ayrı gösterilir)
- [x] `effective_independent_episodes`: distinct `(symbol|side|setup_type|signal_bar_ts)` count — 15k satır ≠ 15k bağımsız sinyal

### W3-T3 — Shadow observe-only güvencesi + A/B recorder
- [x] Guard test: `SHADOW_APPLY=true` olsa bile `position_size/leverage/max_loss` değişmiyor (RiskManager shadow'dan izole)
- [x] `SHADOW_APPLY=false` default — `.env.example`'da zaten mevcut, confirm edildi
- [x] `shadow_ab` tablosu: her resolved episode'da `risk_multiplier_would_be`, `score_delta_would_be`, `actual_outcome`, `actual_net_r` log'lanır (sizing etkisi sıfır)
- [x] `storage.insert_shadow_ab()` metodu eklendi

### Gate B ✅
- [x] Cohort'lar ayrılabilir (legacy ≠ wave epoch)
- [x] Shadow'un sizing üzerinde sıfır yetkisi test ile kanıtlandı
- [x] A/B ledger birikmeye başladı
- [x] **179 test yeşil** (171 → 179)

---

## Block C — Selection integrity

Branch: `w3-blockC-selection`

### W3-T4 — Score validity harness

- [x] `SCORE_AS_GATE` flag added to `Config` (default=`true`, env: `SCORE_AS_GATE`)
- [x] `cfg.score_as_gate` gates the `score < trade_threshold → REJECT/WATCH` branch in `DecisionEngine.decide()`; `True` preserves byte-identical pre-T4 behaviour
- [x] `ShadowLearner.score_bucket_stats(epoch=None)`: buckets resolved shadows into 45-55 / 55-65 / 65-75 / 75+; returns `win_pct`, `avg_r`, `n` per bucket + `monotone_expected` + `sufficient_data` (N≥100) + epoch label
- [x] **T4 Decision recorded**: current epoch N≈34 at freeze — insufficient to prove or disprove score monotonicity. Conservative decision: keep `SCORE_AS_GATE=true`. Gate will be revisited in Block D when N≥100 per bucket is achievable.
- [x] Tests: `tests/test_score_validity_T4.py` (7 tests) — all green

### W3-T5 — Global ranking + correlation-aware allocation

- [x] Config flags added (all default to current behaviour):
  - `GLOBAL_RANKING=false` — two-pass path off by default
  - `RANK_KEY=composite` — rank = score + shadow advisory delta (capped ±5)
  - `MAX_PER_CLUSTER=0` — correlation-cluster cap, 0 = disabled
  - `MAX_CLUSTER_EXPOSURE_PCT=0.0` — cluster notional cap, 0 = disabled
  - `MAX_SAME_SIDE=0` — directional cap, 0 = disabled
- [x] `src/aurvex/allocation.py` (new): `CORRELATION_CLUSTERS` static map, `cluster_for()`, `rank_signal()`, `CandidateSlot` dataclass, `apply_caps()` pure function
- [x] `engine._cycle()`: `if cfg.global_ranking` → two-pass (Pass 1 scan+rank, Pass 2 allocate in rank order); `else` → original first-come loop byte-identical (the else branch is the unchanged original code)
- [x] Opportunity-cost metric: when `GLOBAL_RANKING=true`, logs `opp_cost` DEBUG line when best-rejected rank > worst-open rank
- [x] Golden invariant: `GLOBAL_RANKING=false` (default) → original `else` branch runs — cannot diverge from pre-T5 behaviour by construction
- [x] Tests: `tests/test_global_ranking_T5.py` (22 tests) — all green

### Gate C ✅
- [x] Score predictivity measured (T4 decision: gate stays True, N insufficient)
- [x] Global ranking available behind flag (default off, safe to turn on)
- [x] Cluster + directional caps implemented and test-proven
- [x] First-come behaviour provably unchanged at default flags
- [x] **208 tests green** (179 → 208, +29 new)

---

## Block D — Real-data validation

*(to be filled after Block C gate — gated behind real walk-forward passing OOS PF≥~1.3)*

---

## Buğra Primary Gate — score/Shadow demoted to support (Blocks A–D)

**Date:** 2026-06-25 · **Mode:** paper (live permanently OFF) · **Branch:** `claude/bugra-primary-gate-fpye7s`

The Buğra 5-condition signal is now the **primary entry gate**. Score/Shadow are a
**support** layer (ranking + risk modulation), never a veto. Integrity-preserving by
construction: removing the unvalidated score veto is safe; all score-*direction*
behaviour follows **measured** edge, defaults to neutral, and is loudly visible.

### Predictivity verdict at this run

Clean-core epoch N is still thin (offline demo/backtest snapshot showed
`INSUFFICIENT (N<100)`, buckets non-monotone with negative avg_r — proxy only).
**Consequence:** ranking falls back to the neutral shadow-delta tiebreak (raw score
does NOT order slots) and risk modulation is pinned to neutral (1.0). Nothing
unvalidated is amplified. The score *sign* remains unconfirmed in clean-core.

### Block A — score veto removed
- `score_as_gate` default **True → False** (env `SCORE_AS_GATE` reverts). `decision.py`
  veto branch is dead by default; `shadow_only` gate untouched.
- `min_execution_score` (default **0.0** = OFF): opt-in soft floor → `failed_stage=
  "min_score_floor"`. Not a veto.
- `shadow.track_signal` always tracks executed (`source="paper"`) signals regardless
  of `shadow_min_score` — we measure everything we trade.
- Tests: `test_bugra_primary_gate.py`; legacy veto tests pinned to `score_as_gate=True`.

### Block B — edge-validated ranking
- `global_ranking` default **False → True**; `rank_key` default **composite → "edge"**.
- `allocation.rank_signal` edge mode: monotone-positive → rank by score; anti-monotone →
  rank by realised bucket `avg_r`; insufficient data → neutral shadow-delta tiebreak,
  then deterministic 24h-volume/symbol. `rank_basis()` reports the derivation.
- `Decision.rank` / `rank_basis` populated in two-pass Pass 2.
- Addresses the documented "first-come scan order fills slots with earlier-scanned (not
  highest-rank) signals" ordering root-cause (~42% risk-utilisation). Exposure-cap math
  unchanged (out of scope).
- Tests: `test_edge_ranking.py` (incl. the anti-monotone integrity test).

### Block C — score/Shadow → risk/leverage/margin modulation (new)
- `RiskManager.evaluate(risk_multiplier=1.0)`, hard-clamped `[0.5,1.5]`, scales the risk
  **budget** only; every cap + liq-safety binds after. Default 1.0 → **byte-identical**
  sizing (T1 golden tests unchanged).
- `score_risk_multiplier` `[0.8,1.2]` from measured bucket `avg_r` (anti-predictive →
  down-sizes high score). Engine: `clamp(m_shadow * m_score)` gated behind
  `risk_modulation_enabled` (default **False**). Components persisted to Decision + Trade.
- C5 preflight: engine start logs + Telegrams the predictivity verdict and whether
  modulation is live or pinned neutral — never silent.
- Tests: `test_risk_modulation.py`.

### Block D — surfaces
- Funnel: "ranked out" reason (capacity), persisted via additive `funnel.ranked_out`
  column; non-trades attribute to their real stage, never `score_threshold`.
- `_trade_dict` + Telegram show rank/rank_basis + applied risk multiplier; score labelled
  as a rank/risk input, not a gate. `/api/score_validity` returns the verdict badge.
- `daily_summary` carries a predictivity line.
- Tests: `test_dashboard_surfaces.py` + funnel/telegram extensions.

### Test delta
- Suite **208 → 346 green** (+138 incl. new Block A–D tests). Parity preserved; default
  sizing byte-identical; live stays OFF (`LiveExecutor._send_order()` still `SIMULATED`).
- Offline `demo`, `backtest`, `walkforward`, `dashboard` all run clean.
