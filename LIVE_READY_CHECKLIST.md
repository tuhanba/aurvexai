# LIVE READY CHECKLIST — infrastructure vs strategy

> **Infrastructure live-ready ≠ strategy live-ready.** This checklist keeps the
> two separate on purpose. Passing every infrastructure row below still does
> NOT authorize live trading: the EVIDENCE GATE (strategy section) must pass
> independently, and Stage 3 (real order code) requires its own owner-approved
> wave. Real order sending is OFF; `LiveExecutor._send_order()` is a SIMULATED
> stub.

## 1. Three-factor live lock (all required, independently)

Live mode can only be reached when **all three** factors are present. Any one
missing keeps the engine in paper.

| # | Factor | Where | Notes |
|---|---|---|---|
| 1 | `LIVE_ENABLED=true` | `.env` | Default `false`. Config-level master switch. |
| 2 | `LIVE_HUMAN_CONFIRM=<token>` | `.env` | Human-chosen token; never committed. |
| 3 | `/livemode confirm <token>` | Telegram commander | Token must match factor 2. |

The confirmed request is written to `data/mode_request.json` and applied
**only on restart** — there is no hot-switch into live. `/papermode` reverses
the request the same way. Even with all three factors satisfied, the executor
still sends **no real orders** until Stage 3 code exists (it does not).

## 2. ROADMAP Phase-4 preconditions (infrastructure)

From `ROADMAP.md` — required before any live execution adapter is even built:

- [ ] Positive, **stable** expectancy across paper / shadow / backtest.
- [ ] Real ccxt order adapter behind the existing `LiveExecutor` interface:
      partial fills, order timeout, retries, reconciliation, emergency stop.
      **(Not written — Stage 3, not authorized in any pack to date.)**
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

## 5. Bottom line

**Real order sending is OFF; Stage 3 requires a separate owner-approved
wave.** Infrastructure is live-ready in the narrow sense that the lock,
parity, read-only adapter and dry-run validation exist and are tested — but
the strategy evidence gate is failed/withheld, so live promotion is blocked
by design.
