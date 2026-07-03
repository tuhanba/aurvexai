# LIVE READY CHECKLIST — infrastructure vs strategy

> **Infrastructure live-ready ≠ strategy live-ready.** This checklist keeps the
> two separate on purpose. Passing every infrastructure row below still does
> NOT authorize live trading: the EVIDENCE GATE (strategy section) must pass
> independently. Since the owner-authorized Stage-3 wave (2026-07-03) the real
> order adapter EXISTS (`live_orders.py`) — but it is disarmed by default and
> real sending requires the full five-gate lock below.

## 1. Five-gate live lock (all required, independently)

Real order sending happens only when **all five** gates are open. Any one
missing keeps every order SIMULATED.

| # | Gate | Where | Notes |
|---|---|---|---|
| 1 | `LIVE_ENABLED=true` | `.env` | Default `false`. Config-level master switch. |
| 2 | `LIVE_HUMAN_CONFIRM=<token>` | `.env` | Human-chosen token; never committed. |
| 3 | `/livemode confirm <token>` | Telegram commander | Token must match gate 2; applied only on restart via `data/mode_request.json`. |
| 4 | `LIVE_SEND_ORDERS=true` | `.env` | Default `false`. Stage-3 arming switch — exists so pre-Stage-3 setups with gates 1–3 set stay simulated until this explicit opt-in. |
| 5 | Binance API keys (TRADE-ONLY) | `.env` | Withdraw-capable keys are flagged `unsafe_key` by the Stage-1 self-check. |

`/papermode` + restart reverses gate 3 the same way it was set. The adapter
also self-trips (sticky until restart) on: cancel failure, timeout hard cap,
or any protection-placement failure — after flattening the position.

## 2. ROADMAP Phase-4 preconditions (infrastructure)

From `ROADMAP.md` — required before any live execution adapter is even built:

- [ ] Positive, **stable** expectancy across paper / shadow / backtest.
- [x] Real ccxt order adapter behind the existing `LiveExecutor` interface:
      partial fills (accumulated across retries), order timeout/retry
      (Stage-2 policy table), reconciliation, emergency stop.
      **(Stage-3 wave, 2026-07-03 — `live_orders.py`, 22 dedicated tests,
      disarmed by default.)**
- [ ] Private Binance key in `.env` only (never in code/git/logs).
- [ ] Start in canary mode (`LIVE_CANARY_RISK_PCT`) with minimal size.
- [x] Three-factor lock (Section 1) implemented and tested.
- [x] Parity tests green — decision unchanged, only execution differs
      (`PAPER_LIVE_PARITY.md`, `test_paper_live_parity.py`).
- [x] Read-only Binance account adapter (Stage 1): GET-class only, fail-soft,
      withdraw-capable key self-check reports `unsafe_key`.
- [x] Dry-run order payload validation (Stage 2): `order_payload.py` +
      `scripts/dryrun_report.py` validate payloads against exchange filters
      without sending anything.
- [x] Daily-loss kill switch + daily profit lock, both additive and mode-agnostic.

## 3. EVIDENCE GATE (strategy — independent of everything above)

Live promotion additionally requires a strategy that has **passed the
Acceptance Bar**. Current verdicts:

| Strategy family | Verdict | Detail |
|---|---|---|
| Directional TA (Buğra scalp, current paper engine) | **NO-GO (formal)** | Measured edge is not positive-stable; numeric score measured ANTI-predictive and demoted from gate (`SCORE_AS_GATE=false`). Paper continues for evidence collection only. |
| Carry | **Conditional-GO, Phase 1 only** | Cross-margin, universe = 5. **NOT yet promoted** — promotion is a separate future wave with its own Acceptance Bar review. |

No strategy currently satisfies the EVIDENCE GATE. Therefore, even with a
perfect infrastructure checklist, **going live is not on the table today**.

## 4. Operational preconditions (deploy host)

- [ ] `/api/binance` reports `keys_absent` or `connected` — **never**
      `unsafe_key`. If `unsafe_key`: stop, rotate to a read-only key.
- [ ] Dashboard auth set (`DASHBOARD_AUTH_USER` / `DASHBOARD_AUTH_PASS`) —
      port 5000 is internet-published.
- [ ] Four dashboard badges healthy (engine loop, data freshness, kill
      switch, mode) after fresh-epoch restart.
- [ ] `HEARTBEAT_STALE_MS` settled from measured p95 cycle time (Task 4 of the
      final execution pack).
- [ ] `LIVE_ENABLED=false` confirmed in the running container env.

## 5. Go-live procedure (when the EVIDENCE GATE finally passes)

1. Confirm the strategy verdict is GO (`PAPER_PERFORMANCE_REPORT.md`
   successor) and this checklist's Section 4 rows are all checked.
2. Create a **trade-only** Binance Futures API key (no withdraw); put it in
   `.env`; restart; confirm `/api/binance` = `connected`, never `unsafe_key`.
3. Set `LIVE_ENABLED=true`, `LIVE_HUMAN_CONFIRM=<token>`,
   `LIVE_SEND_ORDERS=true`, and a small `LIVE_CANARY_RISK_PCT` in `.env`.
4. Telegram: `/livecheck`, then `/livemode confirm <token>`; restart.
5. Watch the first canary trades end-to-end (entry ack, SL/TP resting on the
   exchange, `reconcile` clean); `/papermode` + restart aborts at any time.

## 6. Bottom line

**Real order sending is OFF by default.** The Stage-3 adapter exists and is
tested, but it is disarmed behind the five-gate lock, and the strategy
evidence gate is still failed (directional TA NO-GO; Carry not promoted) —
so live promotion remains blocked by design until the evidence changes.
