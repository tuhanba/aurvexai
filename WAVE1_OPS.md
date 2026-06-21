# Wave 1 — operator runbook & finish gate

Wave 1 repaired measurement/fill/margin integrity and produced a reliable
baseline. Strategy (TP ladder, signal engine) was deliberately **not** changed.

This file holds the parts that must run on the **server** (Docker / secrets /
network) and so could not be run in the build environment, plus the finish-gate
checklist. Commands are **one per line** (Termius-safe, no `&&`).

---

## What landed in code (T1–T7)

| | change | tests |
|---|---|---|
| T1 | Closed-candle discipline: decision path consumes `MarketSnapshot.closed_ltf()` only; ccxt drops the forming bar; `last_price` stays live | `test_closed_candle.py` |
| T2 | Entry-bar lookahead guard + one-fill-per-candle in `simulate_fill(bar_ts=…)` | `test_entry_lookahead.py`, `test_one_fill_per_candle.py` |
| T3 | Shadow dedup (`UNIQUE(symbol,side,setup_type,signal_bar_ts)`), closed-bar/once-per-bar resolution, **net** R, honest dashboard label | `test_shadow_dedup.py`, `test_shadow_learner.py` |
| T4 | Cost-inclusive sizing: full stop nets ~**-1.0R** (not -1.43R) | `test_cost_inclusive_risk.py` |
| T5 | Slot-aware leverage: tight-stop trade no longer hogs margin; 4 slots fill | `test_slot_aware_leverage.py` |
| T6 | Telegram health contract (configured / secret-free) | `test_telegram.py` |
| T7 | `meta.epoch` stamp + deterministic baseline (`scripts/wave1_baseline.py`) | `test_backtest.py`, `test_metrics_storage.py` |

`pytest` is green (104 tests). Offline `python main.py demo` and
`python main.py backtest` both complete. Baseline: `WAVE1_BASELINE.md`.

---

## T0 — freeze the legacy DB (server, before deploying Wave 1)

No history is deleted; this only makes a restore point.

```
mkdir -p backups
```
```
docker compose cp engine:/app/data/aurvex.db ./backups/aurvex_legacy_$(date +%Y%m%d_%H%M).db
```
```
ls -la ./backups
```

Acceptance: a timestamped `.db` file exists under `./backups/` with size > 0.

---

## T6 — Telegram .env propagation (server; never print secret values)

Check the key/chat are present in `.env` and inside the running container:

```
grep -E '^TELEGRAM_BOT_TOKEN=.+' .env >/dev/null && echo TOKEN_SET || echo TOKEN_MISSING
```
```
grep -E '^TELEGRAM_CHAT_ID=.+' .env >/dev/null && echo CHAT_SET || echo CHAT_MISSING
```
```
docker compose exec engine sh -c 'test -n "$TELEGRAM_BOT_TOKEN" && echo CONTAINER_TOKEN_SET || echo CONTAINER_TOKEN_MISSING'
```
```
docker compose exec engine sh -c 'test -n "$TELEGRAM_CHAT_ID" && echo CONTAINER_CHAT_SET || echo CONTAINER_CHAT_MISSING'
```

If `.env` has them but the container does not (stale container), recreate:

```
docker compose up -d --force-recreate engine
```

Verify the token and send one test message (token is in the URL only; the
response carries no token):

```
docker compose exec engine sh -c 'curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"'
```
```
docker compose exec engine sh -c 'curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" -d chat_id="$TELEGRAM_CHAT_ID" -d text="AurvexAI Wave1 test"'
```

Acceptance: `CONTAINER_*_SET`; `getMe` returns `ok:true`; one message arrives;
the dashboard shows Telegram **configured: yes / healthy: yes**; no duplicate
sends; **no secret printed or committed.**

---

## T7 — clean paper epoch (server)

The legacy DB is frozen by T0. Start the new epoch from a clean DB; the engine
writes a `meta.epoch` stamp on first start. (Wave 2 compares against this epoch,
never the legacy history.)

```
docker compose stop engine
```
```
mv ./data/aurvex.db ./backups/aurvex_preepoch_$(date +%Y%m%d_%H%M).db
```
```
docker compose up -d engine
```
```
docker compose exec engine sh -c 'python -c "import sqlite3,json;print(json.load(open(\"/dev/stdin\")) if False else sqlite3.connect(\"/app/data/aurvex.db\").execute(\"select value from meta where key=\x27epoch\x27\").fetchone())"'
```

(Or just confirm `epoch` on the dashboard / via the API once running.)

Regenerate the deterministic baseline any time (offline, no server needed):

```
python scripts/wave1_baseline.py
```

Acceptance: `pytest -q` green; `WAVE1_BASELINE.md` produced; `meta.epoch`
present; live still OFF.

---

## Wave 1 finish gate

- [x] T1–T5 code + new tests green; existing tests green (intentional updates aside).
- [x] Full stop net loss ≈ risk_amount (−1.0R), not −1.43R.
- [x] One tight-stop trade's margin ≤ slot budget; 4 slots can fill (baseline: 0 margin-rejected signals).
- [x] Forming-candle / lookahead / double-count closed; shadow deduped + honestly labelled.
- [ ] Telegram configured + healthy, no duplicate sends, no secret leak — **run T6 on the server.**
- [x] Clean baseline recorded (`WAVE1_BASELINE.md`); `meta.epoch` stamp implemented (run T7 on the server to mark the live epoch).
- [ ] `READY_FOR_PAPER: YES` — set once T6 + T7 are confirmed on the server.
- [x] `READY_FOR_LIVE: NO` (unchanged by design).
