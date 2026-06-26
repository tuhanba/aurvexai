# AurvexAI — Observability & Clarity Wave: Final Paper-Readiness Report

> Executor: Claude Code · Branch: `claude/apply-analyze-merge-monetize-jesrne`
> Grounded at HEAD `6528af1` · Green floor at start: **403 passed**
> Green floor at end: **459 passed, 0 failed**

This wave was presentation, truthfulness and one synthesis module — **no trade
behaviour, sizing, selection, or exit logic was touched**, and **no default flag
was flipped**. Every new layer is additive and report/label-only.

---

## 0. Repo / server parity (Phase 0)

Phase 0 is a **server-side audit** (docker + `curl localhost:5000`) that can only
run on the live DigitalOcean host. This executor runs in an ephemeral cloud
clone with **no running container or server**, so the server-side half of Phase 0
**must still be run by the owner on the box**. What is verified here:

- **Code parity:** working tree `HEAD == 6528af1`, the exact commit this pack was
  grounded against. All field/function names referenced in the pack were
  re-read from HEAD before editing.
- **Config divergence:** cannot be read from this environment. The owner must run
  the Phase-0 command block (`docker compose exec engine env | grep ...`,
  masked) on the server and compare against `.env.example`. The key rows to
  confirm: `RISK_MODULATION_ENABLED`, `SHADOW_APPLY`, `DASHBOARD_HOST`.

**Owner action still required (Branch A / B):** decide whether risk modulation
stays on. Phase 5's label fix is implemented **either way** and now reports the
*truth* of whatever the flags are, so the dashboard can no longer claim
"observer" while shadow is resizing risk.

---

## 1. Telegram formats (Phase 1)

`trade_opened` now surfaces, from **existing metadata only** (degrades
gracefully when a field is absent):

- **Quality grade** with colour dot — `Quality: A 🟢 (label only — gates nothing)`.
- **Trade Weight** from the applied `risk_multiplier` — `Weight: Normal x1.00`
  / `Reduced x0.70` / `Boosted x1.10`.
- **Configured vs Applied risk** — `Configured: 2.00% (4.000 USDT)` /
  `Applied: 0.39% account risk (0.78 USDT)`.
- **Clip reason** — `Clip: exposure_cap`.
- A compact **"Why opened"** block (Buğra gate, TA 5/5, risk engine allowed, and
  "Shadow reduced risk, did not block" only when modulation actually applied).

Files: `src/aurvex/telegram.py`. Lifecycle TP/BE/SL/closed messages kept their
phone-readable, emoji-keyed, secret-safe form.

## 2. Dashboard (Phase 2)

Already a single page; this added cards/fields rather than restructuring:

- New **Loss Diagnosis** card (`/api/diagnosis`).
- Open-trade cards now show the full field set: grade, weight, configured /
  applied risk, risk utilisation, clip reason, path, notional/margin/leverage.
- **Quality Grade Performance** card now shows per-grade exit-path rates
  (SL / BE / TP2 / TP3) + separation verdict.
- **System State** shows the truthful shadow label + `hard-veto: no`.

No Owner/Engineering/Debug toggles added; dashboard stays strictly read-only.

## 3. CEO / Governor report (Phase 3)

- New **`CEO_SUMMARY`** verdict panel (State / Main issue / Risk action / Slot
  action / Quality action / Shadow action / Next step).
- New **`RECOMMENDATIONS_TIERED`**: IMMEDIATE_FIX / CONTROLLED_EXPERIMENT / LATER.
- `render_report` replaced raw-JSON dumps with a readable indented renderer; the
  structured dict is unchanged for the API/dashboard.
- Guardrail block still reports `report_only` with every `can_*` false.

## 4. Risk visibility (Phase 4)

`configured_risk_pct` / `applied_risk_pct` / `target_risk_usdt` /
`actual_risk_usdt` / `risk_utilisation_pct` / `clip_reason` now surfaced
explicitly on the receipt and the dashboard trade dict, so "why did this open at
0.39% instead of 2%?" is answerable at a glance. **Risk math unchanged.**

## 5. Shadow-mode label — fixed (Phase 5, the one real bug)

`shadow_mode_label(shadow_apply, risk_modulation_enabled)` is the single source
of truth, consumed by `system_state`, the governor `SHADOW_SUMMARY`, and the
governor Telegram summary. Four-combination proof
(`tests/test_shadow_label_consistency.py`):

| shadow_apply | risk_modulation | label                    | hard_veto |
|:------------:|:---------------:|--------------------------|:---------:|
| false        | false           | observer (report-only)   | no        |
| true         | false           | advisory risk apply      | no        |
| false        | true            | advisory risk apply      | no        |
| true         | true            | advisory risk apply      | no        |

`quality_layer` stays `label_only` (that label was always honest).

## 6. Quality grade performance report (Phase 6)

`quality.grade_performance()` computes, per A/B/C/D from stored metadata: N,
winrate, avg_r, profit_factor, net_pnl, **SL / TP1→BE / TP2 / TP3 rates**, plus a
separation verdict (`insufficient_data` until N≥100/bucket). Surfaced in
`/api/quality` and the governor `QUALITY_LAYER_SUMMARY.performance`. The
label-only invariant is asserted: it routes/sizes/blocks nothing.

## 7. Loss diagnosis panel (Phase 7, net-new)

`src/aurvex/diagnosis.py` — a rules layer over existing aggregates (metrics,
shadow, quality buckets, daily-loss budget, slots). Emits a "Main issue" + ranked
findings, each with an advisory action. Thresholds (PF<1.0, PF<0.7,
expectancy<0, shadow avg_r<-0.30, daily-loss>70%, slots-full-and-PF<1.0,
score anti-predictive) **advise; they never act**. Wired into
`governor.build_report` (`LOSS_DIAGNOSIS`), `/api/diagnosis`, and the governor
Telegram summary. Boundary tests in `tests/test_loss_diagnosis_rules.py`.

## 8. Tests (Phase 8)

`python -m pytest` → **459 passed, 0 failed** (was 403). New suites:
`test_shadow_label_consistency.py`, `test_risk_visibility.py`,
`test_loss_diagnosis_rules.py`; extended `test_telegram_format.py`,
`test_quality_label_only.py`, `test_governor_report_only.py`,
`test_dashboard_surfaces.py`. Offline `python main.py demo` completes
end-to-end; `python main.py report` renders the new CEO/tiered/diagnosis output;
dashboard `/` renders (200).

Invariants held: CEO cannot auto-apply / cannot enable live; quality stays
label-only; shadow has no hard veto in any flag combination; governor stays
report-only.

## 9. Status

- **Still paper?** YES (`AX_MODE=paper`, untouched).
- **Live still off?** YES — `LIVE_ENABLED=false`, `_send_order()` stub
  untouched, `READY_FOR_LIVE` hard-coded `NO`.
- **Recommended next controlled experiments** (proposals, not actions):
  accumulate ≥100 resolved shadows/trades this epoch; compare per-grade avg_r to
  test grade separation before any promotion; review
  `missed_by_max_open_trades` outcomes before considering more slots.

```
READY_FOR_PAPER_CONTINUE: YES
READY_FOR_LIVE: NO
```
