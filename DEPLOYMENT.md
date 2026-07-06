# Deployment

Target: a Linux server with Docker, managed from **Termius** (mobile).

> Termius note: commands are listed **one per line**. Do not chain with `&&`.
> Run them one at a time.

## 0. Optional: check the server

```
docker --version
```
```
docker compose version
```
```
python3 --version
```
```
uname -a
```
```
free -h
```
```
df -h
```

## 1. Get the code onto the server

If you push this project to your GitHub repo `tuhanba/aurvexai`, then on the
server:

```
git clone https://github.com/tuhanba/aurvexai.git
```
```
cd aurvexai
```

(If you uploaded a zip instead, unzip it and `cd` into the folder.)

## 2. Create the `.env`

```
cp .env.example .env
```
```
nano .env
```

Fill in only what you need:
- For **paper** with real Binance public data: nothing required (defaults work).
  Leave `BINANCE_API_KEY` / `BINANCE_API_SECRET` blank.
- For **Telegram** alerts: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  To disable Telegram, set `TELEGRAM_ENABLED=false`.
- Keep `AX_MODE=paper` and `LIVE_ENABLED=false`.

Save and exit (in nano: Ctrl-O, Enter, Ctrl-X).

## 3. Build and start

```
docker compose up -d --build
```

This starts two containers sharing one data volume:
- `aurvex-engine` — the paper engine loop
- `aurvex-dashboard` — the dashboard on port 5000

Check status:

```
docker compose ps
```

## 4. Open the dashboard

In a browser:

```
http://<server-ip>:5000
```

Health endpoint:

```
http://<server-ip>:5000/health
```

If the server has a firewall, allow port 5000 (example for ufw):

```
sudo ufw allow 5000/tcp
```

### 4a. Dashboard access security (recommended)

Two additive protections exist; neither changes default behaviour:

1. **HTTP Basic auth** — set both `DASHBOARD_AUTH_USER` and
   `DASHBOARD_AUTH_PASS` in `.env`. Every route then requires the credentials
   except `/health` (the docker healthcheck hits it from localhost). Leave
   them unset and the dashboard stays open as before.

2. **Localhost-only publish + SSH tunnel** — in `docker-compose.yml`, swap the
   port line to the commented alternative:

   ```
   # - "127.0.0.1:5000:5000"
   ```

   The dashboard is then reachable only through an SSH tunnel. From your
   machine (one command, one line):

   ```
   ssh -L 5000:127.0.0.1:5000 user@<server-ip>
   ```

   then open `http://127.0.0.1:5000` locally. Do NOT switch to the
   localhost-only publish while you still rely on direct-IP access — it would
   lock you out until the tunnel is set up.

## 5. Logs

All services:

```
docker compose logs -f --tail=200
```

Just the engine:

```
docker compose logs -f --tail=200 engine
```

Just the dashboard:

```
docker compose logs -f --tail=200 dashboard
```

## 6. Stop / restart

Stop (data volume is preserved):

```
docker compose down
```

Restart after a code update:

```
git pull
```
```
docker compose up -d --build
```

## Helper scripts

Equivalent wrappers live in `scripts/` (run from the project root):

```
bash scripts/start.sh
```
```
bash scripts/logs.sh
```
```
bash scripts/health.sh
```
```
bash scripts/stop.sh
```

## Running without Docker (bare metal)

```
pip install -r requirements.txt
```
```
cp .env.example .env
```

Engine:

```
python3 main.py engine
```

Dashboard (separate shell / tmux):

```
python3 main.py dashboard
```

## Data & persistence

State is a single SQLite file in the `aurvex-data` volume
(`/app/data/aurvex.db`, WAL mode). It survives `docker compose down`. To wipe and
start fresh, stop first:

```
docker compose down
```

then remove the named volume (this is destructive — all paper history is lost):

```
docker volume rm aurvexai_aurvex-data
```

Then `docker compose up -d --build` recreates an empty database.

## Updating data provider

- `DATA_PROVIDER=ccxt` → real Binance USDT-M public data (default, no key).
- `DATA_PROVIDER=synthetic` → fully offline deterministic data (for testing).

## Safety reminder

This deployment runs **paper only**. The live executor is a gated stub and sends
no real orders. Do not set `LIVE_ENABLED=true` without a separate, explicit
decision and the real-order adapter described in
[`PAPER_LIVE_PARITY.md`](PAPER_LIVE_PARITY.md).

## Parallel strategy stacks (donchian + squeeze)

Two validated edges run side by side, each at its own timeframe (donchian can
NOT be sped up — its edge lives only at 4h; squeeze only at 1h; every faster
cell was measured net-negative). Running both maximises trade frequency
without diluting either edge.

- **Primary (donchian_trend, 4h):** the default `docker-compose.yml` stack —
  Telegram commander, dashboard on **:5000**, epoch `don1`.
- **Secondary (squeeze_breakout, 1h, 24h hold):** `docker-compose.squeeze.yml`
  — its own DB volume, dashboard on **:5001**, epoch `sqz1`, Telegram OFF
  (only one engine may poll the bot).

Bring the secondary up alongside the primary (server, one line each):

    docker compose -f docker-compose.squeeze.yml -p aurvex-sqz up -d --build
    curl -s http://127.0.0.1:5001/health

Stop / remove just the secondary (primary untouched):

    docker compose -f docker-compose.squeeze.yml -p aurvex-sqz down

Both run at INITIAL_PAPER_BALANCE=200 in paper: returns are percentage-based,
so 