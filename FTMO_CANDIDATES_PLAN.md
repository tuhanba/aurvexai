# FTMO Candidate Strategies — test plan (explicit rules) & runnable files

Goal: **shorten time-to-target after costs** (reach +10% step-1 / +5% step-2 sooner, net of
commission+swap, without breaching FTMO limits). The current edge is a reference, not a constraint —
we test alternatives against it. Baseline = the live **PDHL** (indices) + **ORB** (metals).

Nothing here changes live settings. Candidates are evaluated only in the Strategy Tester.

## Baseline (reference)

- **PDHL** (GER40.cash, JP225.cash): break of prior-day high/low; stop ATR14×1.5; `TrailStopR=0.5`
  in initial-R; session-close / Friday flatten; no TP.
- **ORB** (XAUUSD, XAGUSD): 00:00–01:00 UTC opening range, first-break-wins, no TP, session-close.
- Runnable baseline over OOS V1–V4 already exists: `validation_batch/v314_baseline/`,
  `validation_batch/v315_candidate/`.

## Candidates (explicit entry / exit / stop / risk)

Each candidate uses the **same account size, leverage, and per-trade risk band** as the baseline,
is weekend-flat, honors the news-filter setting (recorded), and has a **cost gate**: skip a signal
when `spread + round-trip commission` exceeds a set fraction of the planned stop distance.

### C1 — Scalp  *(needs EA mode: `SCALP`)*
- **Instruments:** XAUUSD, XAGUSD (high-liquidity window only; metals spread makes the cost gate decisive).
- **Window:** 13:00–16:00 UTC (London–NY overlap) only.
- **Entry:** break of the last `N`-bar M1 high/low (default N=5) in the window.
- **Stop:** `k × ATR(M1,14)` (default k=1.0), floored at the broker stop level.
- **Exit:** fixed `TP = 1.0–1.5 R`, OR time-stop `T=10 min`, OR window/session close — whichever first.
- **Risk:** same RiskPct band; hard cap `MaxTradesPerDay` (default 6).
- **Cost gate:** require `expected_move ≥ 3 × (spread+commission)`; else skip.

### C2 — Session breakout  *(RUNNABLE NOW — ORB reparam)*
- **Instruments:** all four.
- **Entry:** break of the first `OrbHours`-hour range after a session open `OrbRangeHourUTC`
  (London 07:00, NY 13:00), first-break-wins (`ForceStrategy=ORB`).
- **Stop:** opposite side of the opening range (native ORB).
- **Exit:** session-close flatten; `TrailStopR=0.5` in initial-R.
- **Risk:** baseline band.
- **Runnable sets:** `candidates/sets/C2_sessionbreak_*_lon.set` (07:00) — feed to the `batch` tool.

### C3 — Trend continuation  *(needs EA mode: `TRENDCONT`)*
- **Instruments:** GER40.cash, JP225.cash (trend-friendly indices).
- **Regime filter:** HTF up = price > EMA200(H1) and > prior-day close (mirror for down).
- **Entry:** on a pullback to EMA20(H1)/VWAP, enter on the break of the last minor swing in the
  trend direction.
- **Stop:** beyond the pullback swing, or `1.5 × ATR(H1,14)`.
- **Exit:** ATR-chandelier trail in R + session/weekend flat.
- **Risk:** baseline band.

### C4 — Mean reversion  *(needs EA mode: `MEANREV`)*
- **Instruments:** indices, **range regime only** (`ADX(H1,14) < 20`); avoid news.
- **Entry:** fade an over-extension — short when M5 close > upper Bollinger(20,2) and RSI(14)>70;
  long on the mirror.
- **Stop:** beyond the band extreme, or `1.0 × ATR(M5,14)`.
- **Exit:** TP at the middle band (mean), OR time-stop `T=30 min`, OR session/weekend flat.
- **Risk:** baseline band.

## Evaluation protocol (identical for baseline and every candidate)

1. **Same periods** as the baseline OOS windows (V1–V4), **same account size + leverage**,
   **comparable per-trade risk** (same RiskPct band), **real tick** (`Model=4`), broker offset
   pinned per DST regime (the `batch` tool does this; boundary-spanning windows are split).
2. **Report these together, per candidate per symbol** (one table per experiment cell):
   - **net after cost** (commission + swap + fee included) and `net_ex_top1` (monster check),
   - **time-to-target**: trading sessions/days to reach the FTMO step target at the modeled risk,
   - **drawdown**: max balance and max equity drawdown (vs FTMO overall 10%),
   - **limit violations**: daily-loss 5% breaches, overall 10% breach, and whether the ≥4
     trading-day minimum is met. **Any hard-limit breach before target = FAIL regardless of net.**
3. **Per-symbol only** — never summed into one portfolio number.
4. **Record every tried candidate** in the experiment ledger (`reports` subcommand appends it with
   full settings + results). **Selected** candidates are re-validated on **UNUSED** periods
   (reserve a window outside V1–V4); the `batch` tool's ledger-based examination status prevents
   silently reusing a tuning period as validation.
5. **No fabricated results.** Where a candidate needs an EA mode that does not exist yet, that is
   the required dev/operator step before it can be tester-run (see status tags above).

## What is runnable now vs pending

| Candidate | Status | Runnable artifact |
|---|---|---|
| Baseline PDHL+ORB | ✅ runnable | `validation_batch/v314_baseline/`, `v315_candidate/` |
| C2 session breakout | ✅ runnable (ORB reparam) | `candidates/sets/C2_sessionbreak_*.set` + `batch` |
| C1 scalp | ⏳ needs EA mode `SCALP` | parameter spec above |
| C3 trend continuation | ⏳ needs EA mode `TRENDCONT` | parameter spec above |
| C4 mean reversion | ⏳ needs EA mode `MEANREV` | parameter spec above |

**Operator/dev step for C1/C3/C4:** implement the named mode in a *candidate* EA build (not the live
EA) exposing the inputs above; then generate its tester matrix with
`aurvex_research.py batch --candidate <name> --ea <candidate.ex5> --set-pattern ... --periods <V1..V4>`
and analyze with `reports`. Keep the live EA and live sets unchanged.

## Generate the runnable matrices

```
# C2 session breakout (exists today), London open, over V1–V3 (V4 pending as future):
python3 scripts/aurvex_research.py batch --candidate C2_sessionbreak --ea "Advisors\Aurvex_v314_test_utc.ex5" --symbols GER40.cash,JP225.cash,XAUUSD,XAGUSD --sets candidates/sets --set-pattern "C2_sessionbreak_{sym}_lon.set" --periods "2026.01.05:2026.03.27,2026.03.30:2026.06.30,2026.07.01:2026.08.31" --today 2026.10.11 --ledger research_out/sept2026/experiment_ledger.csv --out validation_batch/C2_sessionbreak
```
