# Governor + Quality + Observability — Aggressive-Paper Rollout Report

This report documents the de-risked task package: flip to an `aggressive_paper`
profile on a clean epoch, add **decision-path-free** observability (quality
label, missed-opportunity outcomes, decision receipts, a read-only governor,
report-only setup-health/risk-throttle, a system-state + security panel), and a
redacted rollback artifact on epoch reset.

Nothing here changes `DecisionEngine.decide()`'s allow/reject behaviour. Buğra
stays the primary gate; score/quality/shadow stay SUPPORT/observe-only. Live
stays OFF.

---

## 1. Pre-flight (Phase 0) — idea → status

Confirmed before any edit:

| Check | Result |
|---|---|
| `pytest` baseline | **361 passed** |
| `score_as_gate` default | `False` (`config.py`) |
| `risk_modulation_enabled` default | `False` (`config.py`) |
| `ShadowLearner.ladder_replay` exists | `True` |
| `_missed_reason_bucket` exists | `True` (`dashboard/app.py`) |
| `decide()` gate order | filters → shadow_only → score-gate (OFF) → min-score-floor (OFF) → risk sizing → ALLOW |

### Idea → already implemented / partial / missing

| Idea | Status at start | Action this task |
|---|---|---|
| Buğra primary gate | implemented | untouched |
| Score advisory (`score_as_gate=false`) | implemented | untouched |
| Leverage-invariant, size-first, ~−1R fee-inclusive sizing | implemented | untouched (re-pinned by tests) |
| Exposure / min-notional caps | implemented | untouched |
| Efficient + slot-aware leverage | implemented | untouched |
| Shadow observer + 0-50/50-100/100+ stages | implemented | untouched |
| No-lookahead, closed-candle, dedup | implemented | untouched |
| Proxy resolution + full-ladder replay | implemented | surfaced side-by-side (Phase 4) |
| Missed-reason bucketing | partial (counts/win%/avgR) | extended to OUTCOMES incl. PF + canonical buckets + `quality_C_D` + `max_open_trades` outcomes (Phase 4) |
| Epoch reset preserving legacy shadow | implemented | **+ redacted rollback artifact** (Phase 1) |
| Risk/margin/liq dashboard fields | implemented | filled gaps; surfaced profile (Phase 2/7) |
| Named `aggressive_paper` profile (200/2%/1-3%/10%) | partial (aggressive surfaces existed; default was 1000/0.5%/3%) | **named profile + resolver, now the default** (Phase 2) |
| Quality grade (A/B/C/D) label | **missing** | **added, LABEL ONLY** (Phase 3) |
| Decision receipts | **missing** | **added (dashboard + concise Telegram)** (Phase 4) |
| Governor read-only report | **missing** | **added `main.py report`** (Phase 5) |
| Setup health + risk throttle | **missing** | **added, REPORT-ONLY** (Phase 6) |
| System-state + security posture panel | partial | **added `/api/system_state`** (Phase 7) |

---

## 2. What was added vs already present

**Added (new files):**
- `src/aurvex/quality.py` — label-only A/B/C/D grade + reasons.
- `src/aurvex/receipt.py` — consolidated opened/rejected receipts + proxy/ladder basis labels.
- `src/aurvex/governor.py` — read-only daily report (`python main.py report [--telegram]`).
- `src/aurvex/analyzers.py` — report-only setup-health + risk-throttle pure functions.

**Extended (existing files):**
- `config.py` — `RISK_PROFILE` resolver (`conservative_paper`/`aggressive_paper`), `MIN/MAX_RISK_PCT`, band assertion, `GOVERNOR_*` + `RISK_THROTTLE_MODE` flags + guardrail asserts.
- `storage.py` — redacted rollback artifact writer; read-only connection mode; `shadow_quality` side table; `set_shadow_reject_reason`.
- `shadow.py` — `missed_reason_bucket` (relocated/shared), `missed_opportunity_outcomes`, `setup_outcome_summary`; carries quality grade on rows.
- `engine.py` — attaches the label-only grade after `decide()` (both paths); stamps slot-loss reasons on tradeable-but-unslotted shadows.
- `executors.py` — carries the quality grade onto opened trades.
- `telegram.py` — concise `decision_receipt` block.
- `dashboard/app.py` + `templates/index.html` — `/api/quality`, `/api/missed_opportunity`, `/api/receipts`, `/api/shadow_basis`, `/api/setup_health`, `/api/system_state`; System State + Security + Observability panels.
- `main.py` — `report` verb; rollback artifact on `reset`.
- Docs: `.env.example`, `README.md`, `CLAUDE.md`.

---

## 3. Test results

```
pytest: 403 passed
```

(Baseline 361 → 403; +42 new tests across Phases 1–7.) Parity tests
(`test_paper_live_parity.py`, `test_no_behavior_change_T1.py`,
`test_leverage_pnl_invariant.py`) stay green; offline `python main.py demo`
completes end-to-end on the aggressive (200 USDT) profile.

New test files:
`test_epoch_rollback_artifact.py`, `test_quality_label_only.py`,
`test_missed_opportunity_outcomes.py`, `test_decision_receipt.py`,
`test_governor_report_only.py`, `test_setup_health_report_only.py`
(+ extensions to `test_aggressive_paper_200.py`, `test_dashboard_surfaces.py`,
`test_telegram_format.py`).

---

## 4. Rollback artifact for this epoch

`python main.py reset` now writes, **before clearing anything**, an artifact to:

```
backups/<EPOCH_LABEL>_<unix_ms>/
  ├─ env_redacted.txt      (.env copy, secret VALUES redacted — only if .env present)
  ├─ config_snapshot.json  (resolved Config, secret fields excluded)
  ├─ git_head.json         (HEAD SHA + branch)
  └─ db_backup/<db file>   (copy of the SQLite DB + WAL/SHM)
```

Example produced during verification (gitignored, not committed):

```
backups/wave3_aggressive_1782436227061
  config_snapshot.json   → telegram_bot_token: ""   risk_profile: aggressive_paper   balance: 200.0
  git_head.json          → sha 2c04d92…, branch claude/exciting-mayer-7pvwee
  db_backup/epoch.db
```

`backups/` is gitignored; existing backups are never deleted (the `<unix_ms>`
suffix makes each unique).

---

## 5. HARD GUARDRAIL confirmations

| Guardrail | Status |
|---|---|
| `LiveExecutor._send_order()` still a `SIMULATED` stub | ✅ untouched |
| No secrets in code/git; `.env` gitignored, only `.env.example` placeholders | ✅ |
| `decide()` mode-agnostic; paper/live/backtest parity | ✅ parity tests green |
| `decide()` allow/reject behaviour unchanged | ✅ no edits to gate logic |
| Quality grade is **LABEL ONLY** — no D-reject, no C→shadow routing, no grade-keyed risk | ✅ tested (`test_quality_label_only.py`) |
| D-grade signal that passes Buğra + risk is still ALLOWED | ✅ tested |
| Toggling grade inputs never flips a decision | ✅ tested |
| Governor imports nothing from the executors' order path; never calls `decide()` | ✅ clean-subprocess + static import-line tests |
| Governor writes no config, no `LIVE_*`, no risk; no DB mutation | ✅ read-only connection; before==after test |
| Governor `READY_FOR_LIVE` always `NO` | ✅ tested |
| Setup-health / risk-throttle are report-only; no setup auto-disabled; no risk write | ✅ tested (`test_setup_health_report_only.py`) |
| `RISK_MODULATION_ENABLED`, `SHADOW_APPLY`, `SCORE_AS_GATE` stay OFF by default | ✅ unchanged defaults |
| Shadow never hard-vetoes | ✅ observe-only |
| Dashboard has no write controls; no endpoint leaks secrets | ✅ all-endpoint secret-sweep test |
| Rollback artifact redaction holds (no `.env` secret value leaks) | ✅ tested |

---

## 6. Readiness

```
READY_FOR_AGGRESSIVE_PAPER: YES
READY_FOR_LIVE: NO
```

**READY_FOR_AGGRESSIVE_PAPER = YES** because: mode is paper, live is disabled,
the active profile resolves to `aggressive_paper` (200 / 2% / band 1–3% / 10%)
with `risk_pct` inside its band, sizing stays leverage-invariant and ~−1R
fee-inclusive, the decision path is unchanged, the epoch can be reset cleanly
with a recoverable rollback artifact, and all observability is decision-path-free.

**READY_FOR_LIVE = NO** by design — live remains structurally OFF
(`LiveExecutor._send_order()` is a stub; `LIVE_ENABLED=false`). Promoting the
quality grade beyond a label, raising slots/leverage, or any live consideration
is deferred to a later, evidence-driven task once the aggressive_paper epoch has
accumulated enough resolved shadows + paper trades to judge edge.

---

## 7. Out-of-scope (explicitly NOT done)

Per the task: the quality grade rejects/routes nothing; the governor has no
trade/risk/live/config-write authority; `RISK_MODULATION_ENABLED` / `SHADOW_APPLY`
/ `SCORE_AS_GATE` were not enabled; nothing auto-adjusts slots/leverage/
thresholds/risk; no setup is deleted or auto-disabled; `LiveExecutor._send_order`
and every `LIVE_*` value are untouched.
