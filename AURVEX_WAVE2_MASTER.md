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

## Block B — Cohorts + Shadow integrity

*(to be filled after Block A gate)*

---

## Block C — Selection integrity

*(to be filled after Block B gate)*

---

## Block D — Real-data validation

*(to be filled after Block C gate — gated behind real walk-forward passing OOS PF≥~1.3)*
