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

This deployment runs **paper only**. A real order adapter exists
(`live_orders.py`) but it is disarmed behind the five-gate lock
(`LIVE_ENABLED` + `LIVE_HUMAN_CONFIRM` + Telegram confirm + restart +
`LIVE_SEND_ORDERS` + keys) — every default keeps orders SIMULATED. Do not
open any gate without reading [`LIVE_READY_CHECKLIST.md`](LIVE_READY_CHECKLIST.md).

## Parallel strategy stacks (donchian + squeeze) — LEGACY option

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
so percent-performance equals any live split — full 200 each just gives cleaner
per-strategy statistics. Live capital allocation is a separate later decision;
note that two engines sharing ONE real Binance account is a live-only
complication (shared margin/positions) to be designed before any live parallel.

## Multi-strategy on ONE account (recommended over the separate stack)

The `STRATEGIES` env runs both validated edges inside a SINGLE engine on ONE
shared balance — one kill switch, one profit lock, one slot pool, one Telegram
commander, one dashboard. Each strategy still enters on its own timeframe and
exits by its own rule (donchian on its 4h channel, squeeze on its 1h 24-bar
time-stop). One position per symbol is enforced across both, so they never
double up. This is the "two friendly systems on one line" deployment and it
supersedes the separate `docker-compose.squeeze.yml` stack (which kept two
independent balances).

On the server, on the primary stack's `.env` (one line each; this is the
validated THREE-leg deployment — squeeze@1h pinned via `u=` to its own
validated 12 coins, squeeze@4h newly harness-accepted on the 17):

    sed -i '/^STRATEGIES=/d' .env
    printf 'STRATEGIES=donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24:u=BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TON+TRX+DOT squeeze_breakout@4h/1d:ts=24\n' >> .env
    sed -i 's/^GLOBAL_RANKING=.*/GLOBAL_RANKING=true/' .env
    sed -i 's/^LTF_LIMIT=.*/LTF_LIMIT=525/' .env
    docker compose up -d --force-recreate
    curl -s http://127.0.0.1:5000/api/system_state

STRATEGY_PROFILE is ignored while STRATEGIES is set. Leave STRATEGIES empty to
return to single-strategy mode. The engine logs `MULTI-STRATEGY mode: ...` on
start; trades carry their strategy's `exit_ltf` so each is managed on its own
timeframe.

### Trade ONLY the validated universe (important)

The edge is coin-specific. The live scanner ranks the top `UNIVERSE_SIZE`
coins by 24h volume, which on a busy day pulls in exotic / newly-listed names
(e.g. WLD, CL, XAG, SPCX) whose breakouts fail far more often — trading them
is trading OFF the validation set and bleeds on false breakouts. The
Phase-4 expansion study validated exactly **17 coins** (meanR +0.334,
t +4.74, n=3,422; adding more measured flat-to-negative). Pin the universe:

    UNIVERSE_SIZE=17
    UNIVERSE_INCLUDE=BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT,BNB/USDT:USDT,XRP/USDT:USDT,DOGE/USDT:USDT,ADA/USDT:USDT,AVAX/USDT:USDT,LINK/USDT:USDT,TON/USDT:USDT,TRX/USDT:USDT,DOT/USDT:USDT,NEAR/USDT:USDT,ARB/USDT:USDT,SUI/USDT:USDT,ICP/USDT:USDT,ATOM/USDT:USDT

Sizing note: donchian's wide (2×ATR) stops make each position large in
notional, so `MAX_PORTFOLIO_EXPOSURE_PCT` (default 200) saturates after ~2
positions at `RISK_PCT=3` — the 6 slots never fill and diversification stays
low (high variance). Lowering `RISK_PCT` to ~1.5 fits 3–5 concurrent
positions under the same exposure cap: same per-trade R-edge, smaller swings,
better diversification.
