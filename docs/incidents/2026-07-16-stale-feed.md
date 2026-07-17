# Incident RCA — 2026-07-16: engine ran LIVE on stale market data, silently

**Status:** root cause identified (code-path analysis, repo @ incident-era HEAD);
fixes shipped in the P0 live-safety sprint (this branch).
**Severity:** critical — 5 real positions managed blind for 4h18m+.
**Owner action during incident:** engine container stopped; all 5 positions
manually flattened on Binance; DB ghost rows closed as `MANUAL_CLOSE` with
NULL close_price / realized_pnl (Binance is the accounting source for them).
Pre-fix DB backup: `~/aurvexai/backups/aurvex_pre_ghost_fix.db`.

## 1. What happened (verified ground truth)

- The engine ran LIVE with 5 open positions while the last closed bar was
  15 487 s (~4h18m) old. It kept cycling every ~5 s on stale data and kept
  producing `setups=1`.
- New entries were prevented **only** because the exposure cap happened to be
  saturated (321%/300%) — an accident of state, not a safety design.
- The complete log history contained **no kline/fetch/candle lines and no
  errors** — the feed died with zero output, in success and in failure.
- The dashboard showed a reconcile MISMATCH; the engine took no action
  (reconcile was report-only).
- The engine's logged balance froze at 196.72 and never changed, even after
  the owner flattened every position on the exchange (balance was an internal
  paper-accounting mirror, never synced from the exchange).

## 2. Market-data path (as-was)

There is **no dedicated fetch thread and no WebSocket**. All market data is
pulled synchronously inside the engine cycle:

```
Engine._cycle()
  └─ scanner.scan() ── CCXTProvider.load_universe() ── ccxt fetch_tickers (REST)
  └─ per symbol: CCXTProvider.get_snapshot()
        ├─ _fetch_klines(sym, tf)  ── ccxt fetch_ohlcv (REST, closed-bar cache)
        └─ fetch_order_book(sym)   ── ccxt REST
```

`ccxt` is used in synchronous mode with `enableRateLimit=True`. A "dead
unsupervised thread" is therefore ruled out for klines; a fully hung
connection is ruled out by the observed ~5 s cycling. The mechanism is the
third candidate: **swallowed exceptions**.

## 3. Root cause

**The data layer was fail-silent by construction, and its degraded mode
("serve the stale cache") was indistinguishable from healthy operation.**

Three code facts combined (all verified in `market_data.py` @ incident HEAD):

1. **Errors were logged at DEBUG, which is invisible at the production
   `LOG_LEVEL=INFO`:**
   ```python
   except Exception as exc:
       _log.debug("fetch_ohlcv failed %s %s: %s", symbol, tf, exc)
       return cached
   ```
   The same pattern covered the order-book fetch (`_log.debug(...); return
   None`). Any persistent upstream failure — DNS, TLS, Binance 4xx/5xx ban,
   connectivity loss — produced **zero log output** at INFO.

2. **On failure the kline path returned the last good cache ("best-effort")**,
   so downstream code kept receiving structurally valid, ever-older candles.
   Setup detectors happily computed on them (`setups=1`), and the closed-bar
   cache kept re-serving the same bars forever.

3. **There was no success-path logging either** — no per-cycle fetch summary
   line existed, so a healthy cycle and a fully dead cycle produced the same
   log shape. `data_age_ms` was written to the DB heartbeat but appeared in no
   log line and gated nothing engine-side.

### Why the existing stale-entry guard did not save the day

`STALE_ENTRY_GUARD_BARS` (default 3 × the smallest strategy TF) only skips
**new entries per-symbol** and only for symbols whose snapshot was actually
built that cycle. It:

- never halts the engine into an explicit manage-only state,
- never alerts (one `log.warning` per symbol at most, nothing to Telegram),
- does nothing for symbols whose snapshot returned `None` (order-book failure),
- does not invalidate the kill switch / risk state, which kept reading "OK"
  from stale numbers.

With the deployed multi-TF legs the incident data (4h18m stale on a 1h leg)
*should* have tripped per-symbol skips — the absence of even those warnings in
the log indicates the snapshot path was failing before the guard could run
(order-book fetch failing → `return None` at DEBUG → symbol silently dropped),
while `setups=1` per cycle came from whatever symbol still had a cached-kline +
live-orderbook combination. Exact upstream error type (DNS vs ban vs network)
is not recoverable from the container logs **because nothing was logged** —
that fact is itself the core finding.

### Contributing causes

- **Reconcile was report-only** (`live_orders.reconcile()` returns a dict;
  nothing consumed it for action). DB ghosts persisted; dashboard MISMATCH had
  no teeth.
- **Balance was never synced from the exchange** — the engine's balance is a
  DB meta mirror moved only by its own simulated fills, so it froze at 196.72
  and every risk % computed from it was fiction.
- **No background-task supervision**: nothing distinguished "quiet because
  healthy" from "quiet because dead" anywhere in the system.
- **Exposure cap enforced on entry notional only** — position drift took real
  exposure to 321%/300% with no alert; ironically this accident was the only
  thing blocking new blind entries.
- **Ops trap:** `docker compose up -d dashboard` side-started the stopped
  engine via `depends_on: engine`.

## 4. Fixes (this branch — P0 live-safety sprint)

| # | Fix | Where |
|---|-----|-------|
| 1 | Feed watchdog: per-TF closed-bar age, OK→ALERT→HALT; HALT blocks ALL new entries (manage-only), Telegram critical, dashboard badge, risk state UNKNOWN | `watchdog.py`, `engine.py` |
| 2 | Every data-layer exception logs at **ERROR** (first per cycle with traceback) + per-cycle counters | `market_data.py` (`FetchStats`) |
| 3 | One INFO feed-summary line **every** cycle (fetches, cache hits, bars, errors, latency, ages, state) + `data_age`/feed state on the heartbeat log line | `engine.py` |
| 4 | Reconciliation = enforcement: startup + every `RECONCILE_INTERVAL_SEC`; ghosts closed (`EXCHANGE_RECONCILE`, NULL PnL), unknown positions CRITICAL (never adopted), qty mismatches CRITICAL | `reconcile.py`, `storage.close_trade_reconcile` |
| 5 | Protective stops must REST on the exchange: verified every pass; missing → recreated reduce-only STOP_MARKET (armed) or CRITICAL naked-position alert (disarmed). Entry path already places SL as closePosition STOP_MARKET | `reconcile.py`, `live_orders.place_protective_stop` |
| 6 | Wallet sync from exchange (live): balance mirror follows the exchange wallet via ledger (`EXCHANGE_SYNC`); stale wallet reading = health failure + alert | `reconcile.py`, `engine.py` |
| 7 | Exposure cap enforced on **mark-to-market** notional incl. drift; breach blocks entries + critical alert; effective account leverage logged every cycle with alert ceiling | `engine.py` |
| 8 | Background tasks supervised: crash → restart with exponential backoff + alert + heartbeat counter | `engine._supervised` |
| 9 | Log hygiene: rotating file logs, noisy libs capped at WARNING, compose json-file rotation | `logging_setup.py`, `docker-compose.yml` |
| 10 | Compose: `depends_on` removed — dashboard operations can never side-start the engine | `docker-compose.yml` |

## 5. Verification

Exit-criteria tests live in `tests/test_p0_live_safety.py` (stale-feed halt,
supervisor restart, reconcile ghost-close, protective-stop recreation,
exposure-breach block — each simulated and asserted). Full suite green; results
pasted in the PR description.

## 6. Follow-ups (Phase 1, not P0)

- Leg-level live-strategy verdicts vs the walk-forward NO-GO evidence (§3 of
  the task pack) — the strategies that were running blind are directional TA.
- band_walk missing from the dashboard strategy panels — audit in the
  dashboard redesign review.
- Consider WebSocket klines with REST fallback only after the watchdog has
  proven itself (observability first, transport second).
