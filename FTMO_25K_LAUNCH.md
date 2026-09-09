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

## 1. MT5 — install the EA (v2.7)

1. **File → Open Data Folder → MQL5 → Experts**; copy in `AurvexFTMO.mq5` (v2.7).
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
| BTCUSD | 0.30 | 0.3 | 0 | 24 | ORB |

Why these numbers:
- **Core = gold + silver + BTC (all ORB)** — the three instruments with a real
  standalone ORB edge (honest +0.20 / +0.16 / +0.16R). BTC is weekday-only (the
  EA blocks weekends automatically) and needs `ForceStrategy=ORB` because crypto
  auto-detects to PDHL, which is negative. Verify BTC's 0.01-lot risk is ≤ ~0.5%
  on the $25k; if the crypto spread runs too wide at KAPI-1, drop it.
- **Metals 0.35%** (gold + silver) — the strongest edge, weighted highest.
- **Indices 0.25–0.30%** — weak on their own; kept small purely for
  variance-reduction (diversification raises the pass rate). US100 is the weakest
  (honestly ~0/negative), so it gets the lowest weight.
- **Trailing:** metals (gold+silver) = 0 (their edge is the rare runner — a trail clips
  it); indices = 0.5 and BTC = 0.3 (per-instrument optima — BTC is not a metal,
  its distribution likes a small trail, which also keeps its edge alive at the
  wider crypto spread).
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

### BTC multi-session (v2.5 — the speed upgrade, after KAPI-1)
BTC has genuine trend-neutral ORB edge at three UTC sessions (00, 03, 13 — long
and short both positive at realistic cost; see `FTMO_BTC_MULTISESSION.md`). The EA
supports this per-chart via `OrbRangeHourUTC`: open **three BTCUSD charts**, set
`OrbRangeHourUTC` to `0`, `3`, `13` respectively, each `ForceStrategy=ORB`,
`TrailStopR=0.3`, and **`RiskPct=0.10`** (three charts × 0.10 = the same 0.30% total
BTC risk, just spread over 3 sessions = ~3× the BTC trades, faster compounding at
no added risk). Verify each chart's log shows its `orbHourUTC=`. **Do this only
after KAPI-1 confirms BTC's live single-session edge and spread** — it is new code
that should be watched on the first days. To start, run BTC single-session
(one chart, `OrbRangeHourUTC=0`, `RiskPct=0.30`).

### Gold low-volatility-day filter (v2.6 — the edge upgrade, demo-verify first)
Out-of-sample tests show the GOLD ORB roughly doubles its expectancy (+0.19R →
+0.36R OOS) if it **skips dead low-range days**: only trade when gold's opening-hour
range is at least the trailing-20-day median range (see
`FTMO_PER_INSTRUMENT_RESEARCH.md`). The EA ships this as `MinRangeMedMult`
(default **0.0 = off**). To enable, set **`MinRangeMedMult = 1.0` on the XAUUSD
chart only** — leave silver, BTC and indices at 0 (they show no benefit). It is
causal (computed from prior days), but it is **new code and it halves gold's trade
count**, so run it on the demo first: confirm the Experts log shows
`minRangeMult=1.00` and that the "skip (low-vol day filter)" messages fire only on
genuinely quiet mornings. Let KAPI-1 confirm it on real fills before trusting it on
size. At launch you may keep it **off** (0.0) for the simplest, already-validated
baseline and turn it on once the demo/KAPI-1 looks clean.

The same filter exists for the index PDHL side as `PdhlMinRangeMedMult` (default
0.0 = off). Research shows **JP225 is a genuine +0.09R OOS edge** (not the
"breakeven" the old roster said) and its vol-filter adds a stable +0.03R, so after
KAPI-1 you may set `PdhlMinRangeMedMult = 1.0` **on the JP225 chart only** (GER40
and NAS100 show no benefit — leave them at 0). Same rule: demo-verify first, watch
the log line `pdhlMinRangeMult=1.00` and the skip messages.

### v2.7 execution guard + profit-lock (risk layer, default OFF)
The edge is not in entry timing (proven — see `FTMO_PER_INSTRUMENT_RESEARCH.md`),
so v2.7 improves the **risk/execution** layer, where the edge actually lives. Both
default OFF (parity preserved); tune on live/KAPI-1 first — they cannot be
backtested (proxy data has no spread).
- **`MaxSpreadPct`** — the EA stands down (cancels pendings, does not arm) whenever
  the live bid-ask spread exceeds this % of price. It only ever *removes* a trade,
  never adds risk. Set it **below** each instrument's cost break-even
  (`FTMO_LIVE_CONFIG.md`) — a safe start once KAPI-1 shows real spreads is roughly:
  gold/silver 0.05, BTC 0.06, indices 0.04. Leave at 0 until you have measured live
  spreads, or you may skip everything.
- **`PhaseTargetPct` / `NearTargetPct` / `NearTargetMult`** — profit-lock: when
  equity is within `NearTargetPct` of the phase target, per-trade risk is cut to
  `NearTargetMult`, so a near-pass isn't given back. To use, set
  `PhaseTargetPct=10` (Phase-1) or `5` (Phase-2); defaults 1.5 / 0.5 mean "within
  1.5% of target, trade at half risk". Off (0) by default.

## 4. Turn it on and VERIFY

1. Top toolbar **"Algo Trading"** button green.
2. Each chart corner shows the EA name with a **😊** (not a sad face).
3. **Toolbox → Experts** tab shows one line per chart:
   `AurvexFTMO v2.7 on <SYM> strat=... minRangeMult=0.00 pdhlMinRangeMult=0.00 maxSpread=0.000 phaseTgt=0.0 offsetH=3 initBal=25000.00`
   - **`initBal=25000.00`** on every line (if it says 10000 or 100000 → STOP, fix
     AccountSize).
   - **`offsetH=3`** (FTMO server is UTC+3; timezone fix working).
   - Metals show `strat=ORB`, indices `strat=PDHL`, BTC `strat=ORB`. The two
     `minRangeMult` fields are `0.00` unless you enabled the gold/JP225 filters.

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

**Allocation recommendation to confirm at KAPI-1** (deep risk-allocation analysis,
`FTMO_PORTFOLIO_RESEARCH.md`): the research now finds **NAS100/US100 is dead
weight** (negative expectancy; dropping it does not lower the pass rate) and
**JP225 is a genuine edge** worth **more** weight (~0.45 vs 0.30). If KAPI-1's real
fills agree, zero-weight US100 and raise JP225. Keep silver despite its wild swings
— its rare monster winners are the biggest in the book. Don't re-weight real money
mid-challenge; apply this on the next challenge or once live data confirms it.

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
