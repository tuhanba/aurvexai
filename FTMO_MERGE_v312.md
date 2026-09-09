# AurvexFTMO v3.12 — the merge (hardened v3.11 + validated strategy)

`mql5/AurvexFTMO_v3_12_merged.mq5`. A friend hardened our EA into a "v3.11" rewrite
with genuinely better operational engineering. This merges **their robustness** with
**our validated strategy**, and is a **reviewed skeleton — compile (F7) + demo-verify
before any live use.** The live account stays on the current EA until the demo is clean.

## What was taken from the v3.11 hardening (kept as-is)
- **Restart-safe state** via GlobalVariables — traded-today, Friday-flat, trailing
  state, the planned entry/SL, and the FTMO day baseline all survive an EA/terminal
  restart. (Our old EA reset these on restart.)
- **Automatic DST** — CET/CEST for the FTMO daily reset and EST/EDT + CET for the
  index cash-session gates, computed from the date. **Removes the manual
  winter/summer session shift** (a recurring error source).
- **`OnTradeTransaction` fill capture + planned-SL original-R** — the true risk basis
  is preserved even when the fill slips from the planned entry.
- **Margin validation, retcode checks, broker freeze/stops-level guard,
  `OrderCalcProfit`-based sizing** — production-grade execution safety.
- **`RequireAccountSize`** — refuses to start with AccountSize ≤ 0 and rejects an
  AccountSize that conflicts with the persisted initial balance.
- **Spread guards** (`MaxSpreadPoints`, `MaxSpreadToStopPct`) — the %-of-stop form is
  a smarter spread guard (normalised to the trade's own risk); on by default at 12.5%.

## What our validated-strategy layer adds
- **`OrbRangeHourUTC` + per-session effective magic** (`g_magic = Magic +
  OrbRangeHourUTC`) — enables BTC multi-session and **fixes the same-symbol
  order-collision** (charts never manage each other's orders). `OrbRangeHourUTC=0`
  ⇒ `g_magic=Magic`, unchanged for standard charts.
- **`MinRangeMedMult`** — GOLD low-vol-day filter (OOS +0.19→+0.36R). Default off.
- **`PdhlMinRangeMedMult`** — JP225 low-vol-day filter. Default off.
- **`PhaseTargetPct`/`NearTargetPct`/`NearTargetMult`** — profit-lock (cut risk near
  the phase target). Default off.
- **`JournalTrades`** (default ON) — one CSV row per entry with the setup context
  (opening range, the median the filter would see, spread at arm + fill) for KAPI-1
  retro-testing. Passive.

## The harm analysis — why PDHL back-scan is OFF by default
v3.11's `PrevTradingDayRange` scans back up to 10 days, so on a **Monday it trades
off Friday's range** (and after a holiday, off a stale range). Our validated backtest
never included that regime. Measured directly, the **extra** back>1 trades are:

| index | back==1 (calendar, validated) | back>1 (the extra Monday/holiday trades) |
|---|---|---|
| GER40 | +0.023 | **−0.062** (net negative) |
| NAS100 | −0.014 | **−0.022** (net negative) |
| JP225 | +0.055 | +0.168 (positive) |

The extra trades are **net-negative on GER40 and NAS100** — real harm. So the merge
adds `PdhlUseBackScan` (**default false = validated calendar prior-day, skip Monday**);
set it true only if you deliberately want the Monday regime (and only JP225 showed a
positive there — confirm on KAPI-1 first).

## Is there any harm from adopting the merge?
- **Strategy/decision logic:** none — the validated entries are unchanged; the drift
  (back-scan) is off by default, and the filters/profit-lock are off by default.
- **Execution:** strictly safer (margin, retcode, freeze-level, restart-safety).
- **The only real risk is an integration bug** in the new code — mitigated by: it is
  a separate file (live EA untouched), it must compile clean (F7), and it must be
  **demo-verified first**. Do not promote to the live/challenge account until the demo
  shows clean logs, correct fills, and the journal writing.
- **`MaxSpreadToStopPct=12.5` is ON by default** and will skip some trades the
  spread-free backtest took. That is prudent live, but it is a behaviour change — set
  it to 0 if you want to first reproduce the pure validated behaviour on demo.
- **`AccountWideEmergencyFlatten=true`** closes the entire account on a guard breach
  (not just this symbol). Correct for a dedicated FTMO account; set false if the
  account holds anything else.

## Deploy (demo first)
1. Copy `AurvexFTMO_v3_12_merged.mq5` into MQL5/Experts on a **DEMO** account.
2. Compile (F7) → must be `0 errors, 0 warnings` (send me any error text).
3. Attach to the charts with `AccountSize` set, filters off to start
   (`MinRangeMedMult=0`, `PdhlMinRangeMedMult=0`, `PdhlUseBackScan=false`).
4. Confirm the Experts log: `Aurvex v3.12-merged on <SYM> ... journal=on`.
5. Let it run; confirm entries, the journal CSV appears (MQL5/Files), and restart the
   terminal once to confirm state persists.
6. Only after a clean demo: consider promoting, and enabling the gold/JP225 filters.
