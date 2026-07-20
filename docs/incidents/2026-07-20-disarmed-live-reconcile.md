# Incident 2026-07-20 — disarmed-live reconcile killed every trade ("işlem açamıyor")

## Symptom

On the live-labelled deployment, every entry the engine opened was closed within
one cycle. Telegram showed the pattern repeatedly:

```
[LIVE] 🟢 LONG · LINK/USDT:USDT · Donchian Trend · … · risk approved (no block)
[LIVE] ⚠️ HEALTH  🔧 Reconcile: DB row LINK/USDT:USDT was OPEN but the exchange
       is flat → closed as EXCHANGE_RECONCILE (PnL left NULL; Binance is the
       accounting source).
```

Same for SOL and XRP. Result: no position ever stayed open — "trades won't open."

## Root cause

The box was in **live mode but DISARMED** (`AX_MODE=live`, keys present, but
`LIVE_SEND_ORDERS=false`). In that state `LiveExecutor._send_order()` returns a
**SIMULATED** ack — it books the trade in the DB but never sends an order to the
exchange (by design; the five-gate lock keeps real sends off). The exchange
therefore stays flat, which is **expected**.

But `ReconcileEnforcer.enabled` gated only on `mode == "live"` + API keys — **not
on being armed**. So the reconciler treated the flat exchange as the accounting
truth, saw "DB row open, exchange flat", and closed every simulated row as
`EXCHANGE_RECONCILE`. The engine opened (simulated) and the reconciler killed it,
every cycle. The reconcile enforcement (P0.3) was correct for *armed* live; it
was wrong to run its accounting-source steps while *disarmed*.

## Fix (PR — this branch)

- **`reconcile.py`**: new `armed` property (five-gate lock open / adapter
  engaged). The two steps that treat the exchange as the **accounting source** —
  step 1 ghost-close (`EXCHANGE_RECONCILE` / `EXCHANGE_CLOSE`) and step 5 wallet
  balance sync — now run **only when armed**. The exchange-**monitoring** steps
  (unknown position, naked protective stop) still run whenever `enabled`, so a
  real position appearing while disarmed is never silently ignored.
- **`engine.py`**: startup clears a stale `mode_override="live"` when the live
  gates are closed, so a disarmed box can't keep re-entering the half-state.
- **Tests**: regression `test_reconcile_disarmed_does_not_close_simulated_rows`
  (disarmed + flat exchange → simulated rows survive, balance intact, no
  EXCHANGE_RECONCILE); the ghost-close / wallet-sync tests now arm explicitly
  (ghost-close is an armed action). Full suite green (820).

## Not a bug (already fixed in repo)

The same screenshot showed `TP1/TP2/TP3 = 215.196` on the Donchian card — the
unreachable 1000R sentinel of a mechanism-exit leg. `telegram._exit_label`
already maps donchian→"channel break" etc.; the deployed server was running
pre-fix code. It renders correctly after the server updates.

## Correct operating state

Disarmed-live is a confusing half-state. For the validation phase the box should
run in **PAPER** (trades stick, reconcile is off, the validated multi-strategy
book accumulates the track record the live-readiness checklist requires). Real
live requires a funded account **and** the full five-gate arm **and** the paper
track record — not this half-state. Return to paper:

```
git pull origin main
python scripts/apply_fast_paper_env.py
docker compose up -d --build
```
