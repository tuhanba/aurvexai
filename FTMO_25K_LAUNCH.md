# FTMO $25k launch — mistake-proof, step by step (2026-08-31)

A complete ordered checklist for a fresh $25,000 2-Step FTMO Challenge, tuned so
the earlier mistakes (wrong AccountSize, XAGAUD, overnight index entries,
too-high risk) cannot happen again. Do the steps in order; do not skip
verification.

## 0. Buy the right account

- **Size:** $25,000
- **Type:** 2-Step Challenge (NOT 1-Step — its "Best Day" consistency rule kills
  our concentrated big-winner edge)
- **Account:** Standard (weekend-flat; the EA is built for this)
- **Platform:** MT5
- Note the fee — it is refunded with your first funded payout, lost if you
  breach. Keep a runway; never stake money you can't afford to lose on one try.

## 1. MT5 — install the EA (v2.4)

1. **File → Open Data Folder → MQL5 → Experts**; copy in `AurvexFTMO.mq5` (v2.4).
2. Open **MetaEditor**, open the file, press **F7 (Compile)**. It must say
   `0 errors, 0 warnings`. If it errors, send me the text.
3. Log into the **$25k** account (File → Login to Trade Account → the new
   Login/Password/Server from FTMO "Show Credentials").

## 2. Open exactly these charts (H1 timeframe)

`XAUUSD`, `XAGUSD`, `GER40.cash`, `US100.cash`, `JP225.cash`, and optionally
`BTCUSD`. **Do NOT open XAGAUD, XAUEUR or any other quote-currency variant** —
those are different instruments (FX overlay) and were never validated.

## 3. Attach the EA to each chart with these EXACT inputs

**Every chart: `AccountSize = 25000`** (the single most dangerous input — wrong
value = wrong lot size = instant breach). **Every chart: tick "Allow Algo
Trading"** in the Common tab.

| chart | RiskPct | TrailStopR | PdhlSessionStartUTC | PdhlSessionEndUTC | ForceStrategy |
|---|---|---|---|---|---|
| XAUUSD | 0.35 | 0 | 0 | 24 | AUTO |
| XAGUSD | 0.35 | 0 | 0 | 24 | AUTO |
| GER40.cash | 0.30 | 0.5 | 7 | 20 | AUTO |
| US100.cash | 0.25 | 0.5 | 14 | 20 | AUTO |
| JP225.cash | 0.30 | 0.5 | 0 | 6 | AUTO |
| BTCUSD (optional) | 0.30 | 0 | 0 | 24 | ORB |

Why these numbers:
- **Metals 0.35%** (gold + silver) — the real edge, weighted highest.
- **Indices 0.25–0.30%** — weak on their own; kept small purely for
  variance-reduction (diversification raises the pass rate). US100 is the weakest
  (honestly ~0/negative), so it gets the lowest weight.
- **Trailing:** metals/BTC = 0 (their edge is the rare runner — a trail clips
  it); indices = 0.5 (a trail lifts their expectancy).
- **Session gates:** indices only trade while their exchange is open (summer/UTC
  values below). Metals/BTC stay 0/24 — ORB is already time-gated.
- **Built-in de-risk (v2.4, leave the defaults):** the EA automatically shrinks
  per-trade risk as the account draws toward the floor — to 0.6× past −3% overall
  drawdown, to 0.35× past −6% — so a losing streak can't bust it (survive to
  recover). Inputs `DeriskDD1Pct/DeriskMult1/DeriskDD2Pct/DeriskMult2` are on by
  default; leave them. This lifts the pass rate ~+4 points at the same base risk.
- This book Monte-Carlos to **~76% single-attempt pass** (with the de-risk) in
  ~4–5 weeks.

**Winter (late Oct → late Mar): add 1 hour** to the index sessions — GER40 8–21,
US100 15–21 (JP225 stays 0–6). Also set `FtmoResetHourUTC = 23` in winter.

## 4. Turn it on and VERIFY

1. Top toolbar **"Algo Trading"** button green.
2. Each chart corner shows the EA name with a **😊** (not a sad face).
3. **Toolbox → Experts** tab shows one line per chart:
   `AurvexFTMO v2.4 on <SYM> strat=... offsetH=3 initBal=25000.00`
   - **`initBal=25000.00`** on every line (if it says 10000 or 100000 → STOP, fix
     AccountSize).
   - **`offsetH=3`** (FTMO server is UTC+3; timezone fix working).
   - Metals show `strat=ORB`, indices `strat=PDHL`, BTC `strat=ORB`.

## 5. Keep it running

- The gold/silver opening range is the **01:00 UTC** window — the machine must be
  up overnight. A cheap **VPS** (or FTMO's free VPS if eligible) is worth it so a
  closed laptop never costs you a setup. Don't let the PC sleep.

## 6. Hard rules — breaking these is how accounts die

1. **Never close or open a trade by hand.** The EA exits at session close and
   manages the stop. A manual close breaks the edge and corrupts the KAPI-1 data.
2. **Never raise risk to win back a loss.** A modest edge has losing streaks of
   5–8 and losing weeks — that is normal, not a signal. Raising risk in a
   drawdown is the classic blow-up.
3. **No new instruments, no XAGAUD, no tinkering** mid-challenge.
4. Let the guard do its job — it stands the account down at −9% before the −10%
   breach.

## 7. The KAPI-1 check (after ~15–30 trades)

Export the MT5 history (History tab → right-click → Report → save HTML) and run
`FTMO_ACCOUNT_SIZE=25000 FTMO_RISK_PCT=0.35 python scripts/ftmo_mt5_slippage.py
<report.html>`. It gives the realised R per instrument — the true live edge.
Watch US100 and BTC especially; keep what holds, drop what doesn't. Send me the
report and we read it together.

## 8. Honest expectations (partner-to-partner)

- Single-attempt Phase-1 pass ≈ **76%** at this config (with the built-in de-risk); Phase 2 (+5%) is easier.
  Getting funded in one buy is likely but **not guaranteed** — a second attempt
  can happen, and that's a normal cost, not a failure.
- The edge is real but **modest**: the money is in a fat tail of rare big
  winners, so expect stretches of small losses before a runner pays for them.
- Protect your runway. Treat this as a real but long-shot pursuit run **alongside**
  other income, not instead of it. The goal is reachable with discipline and
  patience — not fast, not certain.

You've got a clean, honest, tuned system now. Follow the checklist exactly, let
it run, don't touch it, and we read the live data together at KAPI-1.
