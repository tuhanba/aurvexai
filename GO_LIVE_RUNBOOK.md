# GO_LIVE_RUNBOOK.md — every command, in order

**One command per line. Never chain with `&&`** (Termius mobile paste breaks on
chained commands). Copy a line, paste, run, read the output, then the next.

Companion: `OPERATOR_GUIDE_REGIME.md` (what is on/off and why),
`SYSTEM_STATE.md` (source of truth), `LIVE_READY_CHECKLIST.md`.

---

## PART 0 — Binance API key (do this first, in the browser)

Binance → API Management → Create API:

- ✅ **Enable Futures**
- ❌ **Enable Withdrawals** — never enable this
- ✅ Restrict access to trusted IPs → add your server's IP

Keep the key + secret ready for PART 3.

---

## PART 1 — Get the code

```
cd ~/aurvexai
```
```
git fetch origin
```
```
git checkout main
```
```
git pull origin main
```

## PART 2 — Verify BEFORE writing anything

```
python3 -m pytest -q
```
```
python3 scripts/net_check.py
```

Expected: tests green; net_check says **HEALTHY**.
If net_check says UNHEALTHY → stop, fix the link first (raise
`FETCH_TIMEOUT_MS` / `FETCH_RETRIES`, or move the host closer to Binance).
Trading on a bad link is how you get filled at prices you did not choose.

## PART 3 — Write the config

Dry-run first — nothing is written, you just read the diff:

```
python3 scripts/apply_fast_paper_env.py
```
```
python3 scripts/apply_session_env.py
```

Now apply (each takes a timestamped `.env.backup.*` first):

```
python3 scripts/apply_fast_paper_env.py --apply
```
```
python3 scripts/apply_session_env.py --apply
```

Add the secrets by hand (these scripts never touch secrets):

```
nano .env
```

Fill in:

```
BINANCE_API_KEY=<your key>
BINANCE_API_SECRET=<your secret>
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_CHAT_ID=<your chat id>
DASHBOARD_AUTH_USER=<pick a username>
DASHBOARD_AUTH_PASS=<pick a strong password>
```

Save: `Ctrl+O` → `Enter` → `Ctrl+X`

> Do not leave `DASHBOARD_AUTH_*` empty if port 5000 is reachable from the
> internet — without it anyone can read your account.

## PART 4 — Start in PAPER and confirm the machine is healthy

```
docker compose down
```
```
docker compose up -d --build
```
```
docker compose ps
```
```
docker compose logs --tail=40 engine
```

You are looking for a cycle line like:

```
cycle 12 scanned=17 cand=17 setups=2 allow=1 ... feed=OK risk_state=OK
```

`feed=OK` is the gate. If it is not OK, do not continue.

```
bash scripts/health.sh
```

## PART 5 — Pre-arm audit

```
python3 scripts/live_preflight.py
```

Every line except the five gates should be ✓. The gates are supposed to say NO
at this point — you open them next.

---

## PART 6 — ARM LIVE (real money from here)

Pick a token — any secret word, min 6 chars, no spaces. You will type the SAME
word in Telegram. Replace `MYTOKEN` everywhere below.

Dry-run first (writes nothing, shows the plan):

```
python3 scripts/arm_live_env.py --token MYTOKEN --yes-real-orders
```

Apply (gates 1, 2, 4 + canary sizing):

```
python3 scripts/arm_live_env.py --token MYTOKEN --yes-real-orders --apply
```

```
docker compose up -d --force-recreate engine
```

Gate 3 is the human confirm — it is deliberately interactive. In Telegram,
send to your bot:

```
/live MYTOKEN
```

That is the whole switch: `/live` hot-swaps the executor **immediately, with no
restart**, and persists the decision in DB meta (`mode_override`) so a later
container recreate keeps it. The bot must answer:

```
🔴 LIVE — orders are REAL from this cycle.
```

If it answers `❌ Live switch refused: gate closed: ...`, that message names the
remaining gate — fix it in `.env`, recreate, and send `/live MYTOKEN` again.

> **Do not use `/livemode confirm`.** It is the legacy path: it only writes
> `data/mode_request.json`, applies nothing by itself, needs a restart **within
> one hour** to be picked up, and is refused as stale after that. It answers
> "✅ Live mode queued", which reads like success but is not the switch.

## PART 7 — Confirm you are actually live

```
python3 scripts/live_preflight.py
```
```
curl -s http://127.0.0.1:5000/health
```
```
docker compose logs -f --tail=50 engine
```

Dashboard banner must read **🔴 LIVE — REAL ORDERS**. Preflight must show all
five gates ✓. Exit the log follow with `Ctrl+C` (the engine keeps running).

---

## 🚨 EMERGENCY STOP — save this now

```
python3 scripts/arm_live_env.py --disarm --apply
```
```
docker compose up -d --force-recreate engine
```

Real orders stop. Open positions are still managed (stops rest on the exchange).
The reverse path is always as easy as the forward one.

Full stop of everything:

```
docker compose down
```

---

## PART 8 — The first live trades (do this manually)

For the first 3–5 entries, verify each one by eye:

| check | where |
|---|---|
| the order actually reached Binance | Binance → Futures → Order History |
| a protective STOP rests on the exchange | Binance → Positions (SL column) |
| the DB and the exchange agree | `python3 main.py report` → RECONCILE |
| Telegram fired | your phone |

First entries are **canary-sized** (`LIVE_CANARY_RISK_PCT=0.25`, half of the
0.5% base). Once reconcile is clean and fills look sane, go to full base size:

```
python3 scripts/arm_live_env.py --token MYTOKEN --yes-real-orders --full-size --apply
```
```
docker compose up -d --force-recreate engine
```
```
/live MYTOKEN
```

(The recreate restarts on `AX_MODE`; `mode_override` survives it, but re-sending
`/live` costs nothing and makes the state unambiguous.)

---

## PART 9 — Daily routine

```
bash scripts/health.sh
```
```
python3 main.py report
```
```
docker compose logs --tail=50 engine
```

---

## What is running

| | |
|---|---|
| Strategies | donchian@4h · squeeze@4h · ichimoku@4h · band_walk@4h |
| Risk | 0.5% per trade, 8 slots (`JOINT_OPERATING_POINT.md`) |
| Daily profit target | 8% (chop) → 10% (strong trend), then flatten + lock |
| Give-back guard | arms at +4% peak, banks if 33% is given back |
| Daily loss kill switch | −10% |
| Day boundary | 00:00 Türkiye saati |
| Data resilience | 15s timeout + 2 retries |
| Regime stack | observational only (dashboard card, Telegram alerts, drift) |
| Regime matrix/tilt | **OFF** — retracted, not an earn-more lever |

## If trades do not open

Do not guess — read the funnel:

```
python3 main.py report
```

Look at **FUNNEL_AND_REJECTIONS → top_reject_reasons**. That names the exact
gate that is turning candidates away (`stale_data`, `spread`, `slippage`,
`exposure_cap`, `max_open_trades`, `cooldown`, …). Send that line and the cause
is identifiable rather than guessable.
