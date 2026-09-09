# FTMO live configuration — the definitive deploy playbook (2026-08-31)

Single source of truth for running AurvexFTMO correctly, whether rescuing the
current challenge or starting a fresh one. It consolidates the whole research
campaign (`FTMO_TRAILING_RESEARCH.md`, `FTMO_LIVE_FILL_RISK.md`,
`FTMO_INSTRUMENT_UNIVERSE.md`, `FTMO_CHALLENGE_OPTIMIZATION.md`) into the exact
settings, plus an honest statement of what to expect.

## The instrument roster

The breakout edge is a **liquid-precious-metal phenomenon** — the entire FTMO
universe was tested under honest fills and only two survive, with one borderline
probation candidate. Indices are kept for **variance reduction** (diversification
lowers bust probability), not for their own expectancy.

| chart | strategy | role | honest edge |
|---|---|---|---|
| XAUUSD | ORB | **core** | +0.14–0.23R |
| XAGUSD | ORB | **core** | +0.13–0.23R |
| GER40.cash | PDHL | diversifier | ~0 to +0.09R |
| US100.cash | PDHL | diversifier (weakest) | ~0 / negative |
| JP225.cash | PDHL | **real edge** | +0.09R OOS (EA-matching, CI excludes 0); +0.12 with vol-filter |
| BTCUSD | ORB (ForceStrategy=ORB) | **core** | +0.16R (trail 0.3 keeps it alive at wide spread) |

NAS100/US100 is the weakest — the #1 KAPI-1 suspect. XAGAUD, XAUEUR and other
quote-currency variants are NOT the tested instruments (FX overlay) — use only
XAGUSD / XAUUSD.

## Per-chart settings (EA v2.5)

> The launch authority is **`FTMO_25K_LAUNCH.md`** (step-by-step) and
> **`FTMO_FINAL_REPORT.md`** (summary). This table mirrors the final $25k tune.

| chart | RiskPct | TrailStopR | PdhlSessionStartUTC | PdhlSessionEndUTC | ForceStrategy |
|---|---|---|---|---|---|
| XAUUSD | 0.35 | 0 | 0 | 24 | AUTO |
| XAGUSD | 0.35 | 0 | 0 | 24 | AUTO |
| BTCUSD | 0.30 | **0.3** | 0 | 24 | **ORB** |
| GER40.cash | 0.30 | 0.5 | **7** | **20** | AUTO |
| US100.cash | 0.25 | 0.5 | **14** | **20** | AUTO |
| JP225.cash | 0.30 | 0.5 | **0** | **6** | AUTO |

Common to every chart: **AccountSize = your real account size** ($25000 here —
the single most dangerous input to get wrong), Magic 770077, AvoidNews true,
OrbRangeHourUTC 0 (single-session), de-risk defaults on. Session UTC hours are
summer (CEST/EDT); **add 1h in winter** (GER40 8-21, US100 15-21) and set
FtmoResetHourUTC 23. BTC trail is 0.3 (per-instrument optimum; keeps its edge at
the wide crypto spread) — gold/silver stay 0.

## Risk protocol — low, per-instrument, de-risked

Monte-Carlo pass-probability (no FTMO time limit, so slow is free): lower risk
raises the chance of passing per fee paid. On a $25k account the min-lot floor is
low enough to run metals 0.35% / indices 0.25–0.30% / BTC 0.30%, plus the
built-in draw-down de-risk (v2.4) — together ~76% single-attempt pass. Keep the
diversified book (metals + BTC + session-gated indices) — a concentrated book
passes *less* often because variance/bust risk rises. Funded stage: drop to
~0.2–0.3% for survival. Ready post-KAPI-1 upgrades: BTC multi-session and
volatility-conviction sizing (see the final report).

## What was fixed, and why the live account bled

- **v2.2** — gold ORB read the wrong hour on a UTC+n broker (timezone bug). Fixed.
- **v2.3** — index PDHL was arming overnight and filling on thin futures
  breakouts (GER40 at 00:01 UTC, hours before the DAX opens) — a regime the
  Yahoo backtest never contained (cash-session bars only), and the biggest live
  index losers. The session gate confines PDHL to exchange hours. On the live
  sample this alone would have moved the index book from **−$446 to −$91**.
- **XAGAUD** — a wrong-symbol chart (silver/AUD, FX overlay, untested). Close it.

The metals entries were audited and are correct: the 00:00–01:00 UTC opening
range is optimal for both gold and silver, entries arm right after 01:00 UTC,
and late breaks are neutral (no time-stop needed).

## Hard rules (do not break)

1. **Never touch a trade manually** — no early closes, no manual entries. The EA
   manages exit at session close; a manual close both breaks the edge and
   corrupts the KAPI-1 data.
2. **Never raise risk to "win it back"** after a losing streak — that is the
   blow-up. A modest edge has losing weeks; that is normal, not a signal.
3. **Keep the machine up** (PC or VPS) so the overnight metal ORB window (01:00
   UTC) is never missed.
4. **AccountSize must equal the real account size** on every chart.

## The KAPI-1 gate

After ~15–30 live trades, score with `python scripts/ftmo_mt5_slippage.py
<report.html>` (`FTMO_ACCOUNT_SIZE` / `FTMO_RISK_PCT` set to match). It computes
realised R per instrument — the live-adjusted edge. Watch especially whether the
session-gated indices and silver hold up; drop what does not, keep the metals
core.

### Per-instrument cost break-even (the max tolerable round-trip cost)
`scripts/ftmo_cost_breakeven.py` finds the round-trip cost (spread + commission +
slippage, as a fraction of price) at which each leg's OOS edge crosses zero. Read
each instrument's *realised* cost at KAPI-1 against its break-even below — if the
live cost is near or above it, that leg is not viable live.

| leg | break-even cost | note |
|---|---|---|
| JP225 (filter) | **0.204%** | most spread-robust |
| XAUUSD gold (filter) | **0.170%** | the filter more than **doubles** gold's tolerance (0.082% → 0.170%) |
| BTC (trail 0.3) | 0.118% | crypto spreads run wide — the closest-to-margin core, watch it |
| XAGUSD silver | 0.098% | less liquid; watch realised spread |
| GER40 | 0.076% | thin diversifier |
| NAS100/US100 | **0.013%** | below any realistic index spread — expect it to be non-viable live |

This is the quantitative backing for the allocation call: NAS100's edge dies at
almost any real cost, while the gold filter and JP225 are the most cost-robust legs.

## Honest expectations

The edge is **real but modest** (~+0.15R on the metals core, measured over years
of proxy data). That means: ~35% win rate with the money in a fat tail of rare
big winners; **losing streaks of 5–8 and losing fortnights are normal**; getting
funded is **not guaranteed and can take more than one paid attempt** (single-
attempt Phase-1 pass ~55–62%, both phases lower). Funded income is variable, not
a salary. This is a long-shot, discipline-and-capital game — treat challenge fees
as a bounded, repeatable cost, protect a real runway, and never stake money you
cannot afford to lose on any single attempt.

## Data note

Backtests use free Yahoo proxy feeds cached under `data/cache/ftmo/` (gitignored;
re-fetched on a fresh container). They are proxies, not FTMO tick data — the
overnight-index gap is exactly the kind of limitation they carry. Live KAPI-1 is
always the final arbiter over any backtest number here.
