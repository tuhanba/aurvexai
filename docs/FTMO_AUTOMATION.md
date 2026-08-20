# FTMO full automation + Telegram

Two ways to run the edges — pick per your comfort. **Do everything on the FTMO
demo first.** Nothing here should touch a funded account until the demo shows the
fills are good (`scripts/ftmo_slippage_check.py` → GO).

## A) The MT5 Expert Advisor (full automation) — `mql5/AurvexFTMO.mq5`

The EA runs inside your MT5 terminal and does the whole loop by itself:
computes today's ORB (gold) / PDHL (indices) levels, places the buy-stop +
sell-stop orders with **risk-based lot sizing from the broker's tick value**
(so EUR-quoted GER40 is handled automatically), cancels the losing side when one
fills, and **flattens everything at 00:00 UTC**. It also has an FTMO daily/overall
loss guard.

### Install (once) — v2.0 is PER-CHART
1. In MT5: **Dosya → Veri Klasörünü Aç** (File → Open Data Folder).
2. Copy `AurvexFTMO.mq5` into **MQL5 → Experts**.
3. Open **MetaEditor** (IDE button), open the file, press **Derle / Compile** (F7).
   Fix nothing unless it errors — if it does, send me the error text.
4. Back in MT5: drag **AurvexFTMO** onto **each chart you want to trade** — one
   instance per chart: `XAUUSD`, `GER40.cash`, `US100.cash`. Each instance trades
   **only its own chart symbol** and draws its own levels. The strategy is
   auto-detected (metals → ORB, indices → PDHL).
5. In each dialog tick **"Algoritmik ticarete izin ver"** (Allow Algo Trading),
   and the top toolbar **"Algoritmik Ticaret"** button must be green/on.

- `RiskPct = 0.5` (funded) / `1.0` challenge — **equal 1.0% across all four
  charts.** An earlier note suggested cutting gold to 0.75%; that was based on
  naive backtest numbers and is **retracted** — see `FTMO_LIVE_FILL_RISK.md`.
  Gold ORB is the robust, proven edge (survives live-fill modelling); the index
  PDHL edge may be much weaker live (gap-open days that no-chase skips), so do
  not down-weight gold and do not tilt into the indices until KAPI-1 proves the
  live fills.
- `AccountSize = 100000` — **set this to your real account size** so the overall-loss
  floor is stable across restarts (0 = read the balance at first start).
- `ForceStrategy = AUTO` — auto-picks ORB for metals, PDHL for indices. Override only
  if a symbol is misdetected.
- `DrawLevels = true` — green = buy-stop, red = sell-stop, grey dotted = the stops.
- `TrailStopR` — **set this PER CHART, it is instrument-dependent** (see
  `FTMO_TRAILING_RESEARCH.md`): **XAUUSD → 0** (gold is low-win-rate / fat-tail;
  its edge is the rare session-close runner, which a trail clips — no-trail wins
  4/5 OOS folds), **indices (GER40/US100/JP225) → 0.5** (higher win-rate; the
  trail lifts expectancy, wins 4–5/5 OOS folds). Splitting the trail this way is
  ~+11% portfolio expectancy over a uniform 0.5R and restores gold's big-winner
  tail, at zero added risk (downside always capped at −1R). A 0.3R trail tests
  even better for the indices but sits too close to price for real
  spread/slippage — stay at 0.5 live unless demo data confirms 0.3.
- Start with **only the XAUUSD chart** for a few clean days, then add the index
  charts. (One instance per chart; they never touch each other's orders.)

### Safety inputs (v1.1 — leave at defaults unless you know why)
- `DailyStopBufferPct = 1.0` — the guard stops **1% before** the FTMO daily/overall
  floor (so it never actually touches −5% / −10%). On a floor breach the EA now
  **closes open positions AND cancels pendings**, then stands down until the next day.
- `FtmoResetHourUTC = 22` — FTMO's daily-loss window resets at 00:00 Prague time.
  That is **22:00 UTC in summer (CEST)** and **23:00 UTC in winter (CET)**. Set to
  `23` from late-October to late-March. This only moves the guard's daily baseline;
  the trading session stays on UTC (unchanged, as validated).
- `FridayFlattenHourUTC = 20` — closes everything before Friday's market close so
  nothing is held over the weekend (FTMO Standard weekend-flat rule). The EA also
  blocks new entries on Saturday/Sunday.
- `MaxSingleRiskMult = 2.0` — if the broker's minimum lot would force risk above
  `2×` the target, the EA **skips** that trade instead of over-risking (matters on
  small $10k/$25k accounts).
- `AvoidNews = true`, `NewsBufferMin = 2` — the FTMO news rule. Within 2 minutes
  either side of a **high-impact** event for the symbol's currency (USD for
  XAUUSD/US100, EUR for GER40), the EA cancels its pendings and does not arm new
  ones. It reads MT5's built-in Economic Calendar; if the calendar is empty it
  **fails safe** (does not block). Make sure the terminal's calendar is enabled.

### No-chase (v1.2)
If the opening range (ORB) or prior-day range (PDHL) has **already broken before
the EA arms** — e.g. you attach it mid-session, or price gapped — the EA **skips
that symbol for the day** instead of placing a late/reverse order. So a clean
"first break wins" only fires from an un-broken range. On a normal overnight run
this never triggers; it just protects mid-day attaches.

### Watch it (first days)
- The EA prints to the **Uzmanlar (Experts)** tab every action.
- One instance **per chart**; each trades only its own chart symbol and draws its
  own levels. They share the Magic but never touch each other's orders (all queries
  filter by symbol), so there is no double-order risk.
- It only trades its own orders (Magic 770077); your manual trades are untouched.

> ⚠️ The EA is a **reviewed skeleton not yet run on a live terminal** (I can't run
> MT5 here). Expect 1–2 small fixes on first compile/run — send me any error and
> I'll correct it. That's why we start on the free demo, gold-only, and watch.

## B) Telegram (get the signals / EA alerts on your phone)

### 1. Create a bot + get your IDs (5 min)
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → it gives a
   **token** like `12345:AAE...`.
2. Message your new bot once (say "hi").
3. Get your **chat_id**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser → find
   `"chat":{"id":123456789}` → that number is your chat_id.

### 2a. Daily signal tickets (Python, no EA needed)
Put the token/chat_id in `.env` on your server:
```
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=12345:AAE...
TELEGRAM_CHAT_ID=123456789
```
Test:
```
python scripts/ftmo_send_signals.py
```
Automate daily (cron, after 01:00 UTC):
```
5 1 * * 1-5  cd ~/aurvexai && PYTHONPATH=src python scripts/ftmo_send_signals.py
```

### 2b. EA trade alerts (optional)
In the EA inputs set `TelegramToken` + `TelegramChatID`. Then in MT5:
**Araçlar → Seçenekler → Uzman Danışmanlar → "WebRequest'e izin ver"** and add
`https://api.telegram.org`. The EA will message you on every order/flatten/guard.

## How A, B and the manual menu fit together

| You want… | Use |
|---|---|
| Fully hands-off | **EA** (A) on the demo; optionally EA Telegram alerts (2b) |
| Semi-manual, levels on phone | **Telegram daily** (2a) → place orders yourself |
| Fully manual / learning | `python scripts/ftmo.py` menu |
| Score the result (auto) | **`scripts/ftmo_mt5_slippage.py <mt5_report.html>`** — reads an exported MT5 history directly (no manual entry) and gives KAPI 1 GO/NO-GO |
| Score the result (manual) | `scripts/ftmo_slippage_check.py` (from a hand-logged fills.csv) |

### KAPI 1 — auto GO/NO-GO from the MT5 history
Once a handful of trades have closed on the demo:
1. In MT5, open the **History** tab (Geçmiş) → right-click → **Report / Rapor** → save
   the HTML file (Turkish or English report both work).
2. Run: `python scripts/ftmo_mt5_slippage.py path/to/report.html`
   (or `python scripts/ftmo.py` → option **4**).
3. It maps the broker symbols (XAUUSD, GER40.cash, US100.cash, JP225.cash), computes
   each trade's **realised R = profit / risk-$** — which already includes spread,
   slippage, commission and swap — and prints per-instrument + overall expectancy vs
   the ~0.20R backtest edge, with a **GO / MARGINAL / NO-GO** verdict. Needs ~15–30
   trades for confidence. Set `FTMO_ACCOUNT_SIZE` / `FTMO_RISK_PCT` if not 100000 / 0.5.

## The plan (organized)

1. **This weekend:** install the EA (compile), set up Telegram. No trading yet.
2. **Mon:** turn Algo Trading on, EA runs GOLD-ONLY on the demo. Watch the Experts
   tab + Telegram.
3. **~1 week:** check the demo results; add GER40/US100. Run the slippage check on
   the demo trade history.
4. **GO** (fills good, still profitable) → consider funded. **NO-GO** → the lab is
   ready for the next edge. No funded capital before the GO.
