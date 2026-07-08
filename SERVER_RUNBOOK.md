# SERVER_RUNBOOK.md — owner operations, one command per line

Every command below is safe to paste in Termius **one line at a time**
(no `&&` chains). Run everything from the project root (`cd aurvexai`).

## Start

```
bash scripts/start.sh
```

or manually:

```
docker compose up -d --build
```

Expected: two containers (`aurvex-engine`, `aurvex-dashboard`) in
`docker compose ps`, dashboard on `http://<server-ip>:5000`.
`start.sh` refuses to run if `.env` is missing — first time:

```
cp .env.example .env
```
```
nano .env
```

(paste the recommended paper block from `SYSTEM_STATE.md` §6).

## Stop (data preserved)

```
bash scripts/stop.sh
```

## Restart (e.g. after `.env` change)

```
docker compose down
```
```
docker compose up -d --build
```

`.env` is read at container start — a plain `restart` does NOT reload it;
use `up -d --force-recreate` (or down/up) after editing `.env`.

## Logs

```
bash scripts/logs.sh engine
```
```
bash scripts/logs.sh dashboard
```

Healthy engine log line looks like:
`cycle 123 scanned=17 cand=17 setups=1 allow=0 exec=0 open=2 bal=201.40`.
On start, multi-strategy mode logs `MULTI-STRATEGY mode: donchian_trend@4h/1d + squeeze_breakout@1h/4h (shared account)`.

## Health check

```
bash scripts/health.sh
```

or:

```
curl -fsS http://localhost:5000/health
```

Expected JSON: `"ok": true`, `heartbeat_fresh: true`, `data_fresh: true`,
kill switch false, mode `paper`. Four dashboard badges (ENGINE LOOP, DATA,
KILL SWITCH, MODE) must be green/paper.

## Update to the latest code

```
git pull
```
```
docker compose up -d --build
```

## Reset the paper DB (fresh epoch — DESTRUCTIVE, all paper history lost)

```
docker compose down
```
```
docker volume rm aurvexai_aurvex-data
```
```
docker compose up -d --build
```

## Backup the DB (while running is fine — SQLite WAL)

```
docker compose exec dashboard sqlite3 /app/data/aurvex.db ".backup /app/data/backup.db"
```
```
docker compose cp dashboard:/app/data/backup.db ./aurvex-backup-$(date +%F).db
```

If `sqlite3` is missing in the container, stop first, then copy the raw file:

```
docker compose down
```
```
docker run --rm -v aurvexai_aurvex-data:/data -v $(pwd):/out alpine cp /data/aurvex.db /out/aurvex-backup.db
```

## Restore a DB backup (DESTRUCTIVE to current state)

```
docker compose down
```
```
docker run --rm -v aurvexai_aurvex-data:/data -v $(pwd):/in alpine cp /in/aurvex-backup.db /data/aurvex.db
```
```
docker compose up -d --build
```

## Check Telegram

- Bot alive: send `/health` to the bot — it must answer with engine health.
- Other commands: `/status /trades /closed /summary /balance /profile
  /pause /resume /livecheck /papermode /stop`.
- If silent: check `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` in `.env`, then
  `bash scripts/logs.sh engine` for `telegram` lines. Only ONE engine may
  poll the bot (the squeeze parallel stack keeps Telegram off by design).

## Check the dashboard

- `http://<server-ip>:5000` — badges: ENGINE LOOP green, DATA fresh,
  KILL SWITCH off, MODE `PAPER` banner.
- Set `DASHBOARD_AUTH_USER` / `DASHBOARD_AUTH_PASS` in `.env` — port 5000 is
  internet-published; without auth the dashboard is public.
- Stale data now also blocks new entries engine-side
  (`STALE_ENTRY_GUARD_BARS=3`; reject reason `stale_data` in the funnel).

## Check Binance read-only status

```
curl -fsS http://localhost:5000/api/binance
```

- `keys_absent` — fine for paper (public data needs no key).
- `connected` — read-only key working.
- `unsafe_key` — **stop and rotate the key immediately**: it has withdraw
  permission. Never use a withdraw-capable key.

## Paper / live mode notes (safety)

- The system is PAPER by default and must stay paper until
  `FINAL_OWNER_DECISION.md` conditions are met.
- Real orders need ALL FIVE gates: `LIVE_ENABLED=true`, `LIVE_HUMAN_CONFIRM`
  token, Telegram `/livemode confirm <token>` + restart,
  `LIVE_SEND_ORDERS=true`, trade-only API keys. Any one missing → every
  order is SIMULATED.
- `/papermode` + restart reverses live mode the same way it was set.
- Never commit `.env`. Never use a withdraw-capable key.
