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
| JP225.cash | PDHL | diversifier | ~breakeven |
| BTCUSD | ORB (ForceStrategy=ORB) | optional probation | borderline, cost-fragile |

NAS100/US100 is the weakest — the #1 KAPI-1 suspect. XAGAUD, XAUEUR and other
quote-currency variants are NOT the tested instruments (FX overlay) — use only
XAGUSD / XAUUSD.

## Per-chart settings (EA v2.3)

| chart | RiskPct | TrailStopR | PdhlSessionStartUTC | PdhlSessionEndUTC | ForceStrategy |
|---|---|---|---|---|---|
| XAUUSD | 0.5 | 0 | 0 | 24 | AUTO |
| XAGUSD | 0.5 | 0 | 0 | 24 | AUTO |
| GER40.cash | 0.5 | 0.5 | **7** | **20** | AUTO |
| US100.cash | 0.5 | 0.5 | **14** | **20** | AUTO |
| JP225.cash | 0.5 | 0.5 | **0** | **6** | AUTO |
| BTCUSD (optional) | 0.5 | 0 | 0 | 24 | **ORB** |

Common to every chart: **AccountSize = your real account size** (e.g. 10000 for a
$10k account — the single most dangerous input to get wrong), Magic 770077,
AvoidNews true. Session UTC hours are summer (CEST/EDT); **add 1h in winter**
(GER40 8-21, US100 15-21). Metals/BTC stay 0/24 — ORB is already time-gated.

## Risk protocol — why 0.5%

Monte-Carlo pass-probability (no FTMO time limit, so slow is free): lower risk
raises the chance of passing per fee paid. 0.5% → ~55–62% single-attempt pass;
1.0% → ~52%; 2%+ → <35% and high bust risk. **0.5% is the pass-maximising
choice.** Keep the diversified book (metals + session-gated indices) — a
concentrated metals-only book passes *less* often because variance/bust risk
rises. Funded stage: drop to ~0.3–0.5% for survival.

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
