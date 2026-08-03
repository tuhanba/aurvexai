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

### Install (once)
1. In MT5: **Dosya → Veri Klasörünü Aç** (File → Open Data Folder).
2. Copy `AurvexFTMO.mq5` into **MQL5 → Experts**.
3. Open **MetaEditor** (IDE button), open the file, press **Derle / Compile** (F7).
   Fix nothing unless it errors — if it does, send me the error text.
4. Back in MT5: **Gezgin → Uzman Danışmanlar → AurvexFTMO** → drag it onto a
   **XAUUSD, H1** chart.
5. In the dialog tick **"Algoritmik ticarete izin ver"** (Allow Algo Trading),
   and the top toolbar **"Algoritmik Ticaret"** button must be green/on.

### Inputs (start GOLD ONLY)
- `Trade_XAUUSD = true`, `Trade_GER40 = false`, `Trade_US100 = false`.
- `RiskPct = 0.5`, `AccountSize = 0` (uses your balance).
- Symbol names default to `XAUUSD` / `GER40.cash` / `US100.cash` — adjust if yours
  differ.
- Prove gold for a few days, then flip `Trade_GER40`/`Trade_US100` to true.

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
- One EA instance on ONE chart handles all enabled symbols (it selects them).
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
| Score the result | `scripts/ftmo_slippage_check.py` (works for all of the above) |

## The plan (organized)

1. **This weekend:** install the EA (compile), set up Telegram. No trading yet.
2. **Mon:** turn Algo Trading on, EA runs GOLD-ONLY on the demo. Watch the Experts
   tab + Telegram.
3. **~1 week:** check the demo results; add GER40/US100. Run the slippage check on
   the demo trade history.
4. **GO** (fills good, still profitable) → consider funded. **NO-GO** → the lab is
   ready for the next edge. No funded capital before the GO.
