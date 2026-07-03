# Roadmap

The MVP exists to **measure**, not to assume profit. The path to live is gated
on evidence.

## Phase 0 — MVP (done)

Clean-core engine, 5 setups, scoring, 7 filters, risk model, paper executor,
shadow learner (observe-only), funnel observability, SQLite, Flask dashboard,
Telegram, no-lookahead backtester, Docker, 48 passing tests. **Paper-ready.**

## Phase 1 — Collect evidence (now)

Run paper + shadow on the server continuously. Watch:
- Funnel: where signals die, top reject reasons, signals/day.
- Per-setup expectancy (R), profit factor, win-rate — paper **and** shadow
  (including high-score rejects).
- Per-symbol / per-hour breakdowns.

Goal: enough trades per setup to judge edge with confidence. No code changes to
the decision logic during collection — just observe.

## Phase 2 — Tune from data (config-only first)

- Adjust thresholds, ATR buffers, volume ratios, cooldowns via `.env` based on
  funnel + expectancy data. No structural changes needed for most tuning.
- Prune or disable setups that show negative expectancy; double down on winners.
- Backtest every change before paper.

## Phase 3 — Shadow-assisted scoring (opt-in)

- Turn on `SHADOW_APPLY=true` (soft score nudges only, never a hard veto) once a
  setup has ≥ 50 resolved shadows.
- Add the small per-setup risk multiplier at ≥ 100 resolved shadows.
- Keep everything advisory and reversible.

## Phase 4 — Live execution adapter (explicit decision required)

**Adapter status: BUILT (owner-authorized Stage-3 wave, 2026-07-03), disarmed
by default.** `live_orders.py` implements entry + SL/TP placement with
partial-fill accumulation across retries, the Stage-2 timeout/retry policy,
reconciliation, and emergency stop — behind the five-gate lock
(`LIVE_ENABLED` + `LIVE_HUMAN_CONFIRM` + live mode + `LIVE_SEND_ORDERS` +
keys). Remaining before any real arming:
- Positive, stable expectancy across paper/shadow/backtest (**still NOT
  met: directional TA is formally NO-GO** — `PAPER_PERFORMANCE_REPORT.md`).
- Private TRADE-ONLY Binance key in `.env` (withdraw-capable keys are
  flagged unsafe).
- Start in **canary** mode (`LIVE_CANARY_RISK_PCT`) with minimal size. Known
  canary limitation: TP fractions below `step_size` are dropped (the SL
  still covers the whole position) — sizes must clear min tradeable qty.
- Live fill tracking is still bar-model-based plus `reconcile()` drift
  detection; a websocket fill stream is Phase 5.
- Parity tests must still pass (decision unchanged; only execution differs).

## Phase 5 — Hardening & scale (optional)

- WebSocket market data if cycle latency becomes a constraint.
- Prometheus/Grafana metrics export.
- Per-coin parameter optimisation.
- Multi-tenant SaaS: add a `tenant_id` column (SQLite schema already amenable),
  per-tenant config and dashboards, tiered access gated on win-rate.

## Non-goals (deliberately excluded from the core)

Carried over as *lessons learned* from the old engine and intentionally **not**
rebuilt unless they prove measurable value: multi-AI consensus, Friday CEO,
macro/news/sentiment hard vetoes, ML/Ghost/reputation/regime hard gates, Optuna
auto-apply, and complex duplicate veto chains. Simplicity and measurability come
first.
