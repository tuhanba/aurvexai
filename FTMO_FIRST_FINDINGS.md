# First findings from existing data — how to produce them (no fabricated numbers)

This session cannot read the operator's live DB (`C:\Users\pc\AurvexData\aurvex_live_v13.db`) or
run MT5, so the numbers below are produced by the operator running the read-only analyzer. Per our
rule: **no result is fabricated here** — this states the exact command and what it reports.

## Keep v12 and v13 separate

- v13 DB (`aurvex_live_v13.db`, schema 1.3) holds **true-UTC** rows — analyze this one.
- v12 DB (`aurvex_live_v12.db`) holds **server-time** rows — keep separate; do **not** merge. The
  analyzer refuses a 1.2 DB, so pointing it at v12 is safe (it errors rather than mixing).

## One command → the first report

```
python3 scripts/aurvex_research.py collector --db C:\Users\pc\AurvexData\aurvex_live_v13.db --out C:\Users\pc\AurvexData\reports_v13\first
```

`collector_report.md` reports (read-only; refuses a wrong/old/empty DB):

1. **Freshness** — per-symbol tick counts + last UTC; account balance/equity + staleness.
2. **Tick gaps** — spans over the threshold (reset/disconnect holes surface here).
3. **Deals — per-symbol/owner net tally** (ours vs foreign; a tally, not an external reconciliation).
4. **After-cost net (ours)** — gross profit, **commission**, swap, fee, and **NET after cost**, per
   symbol — the cost-after result you asked for.
5. **Spread (clock-proven ticks only)** — per symbol avg spread in price and in points, plus the
   last `spread_points` snapshot.
6. **Data coverage & clock-proven gating** — per symbol: total ticks, **clock-proven** (`utc_time`
   non-empty), **unproven** (empty), and the proven UTC span. **Session / time-of-day results are
   computed from clock-proven ticks only**; unproven rows are excluded and must not seed session
   conclusions. If any unproven rows exist the report flags it explicitly.
7. **Open positions** — correlated with the latest account snapshot (UNKNOWN when flat can't be
   proven), and `last_deal_ticket`.

## Reading it against the goal

- **Spread + after-cost net** per symbol show which instruments are cost-viable (metals carry wide
  spread/commission — decisive for any scalp candidate's cost gate).
- **Coverage / clock-proven** tells you how much of the capture is usable for any time-based
  (session) analysis. Until UTC/DST and restart checks are complete (still pending per your note),
  treat session-level conclusions as provisional and lean on the deal-level after-cost net (which
  does not depend on tick-clock proof).

## Required operator steps (not automatable from here)

1. Finish the **UTC/DST** check (confirm new tick `utc_time` is true UTC; a DST-boundary tick
   converts with its own offset) and the **restart** check (reset the terminal; confirm
   `resume_gap` / `tick_gap` appear and import resumes) — see `mql5/COLLECTOR_VERIFY.md`.
2. Run the command above on the **v13** DB and paste `collector_report.md` back; then we pick
   cost-viable instruments and move to the candidate matrices in `FTMO_CANDIDATES_PLAN.md`.
3. For backtests, confirm the broker holds **real tick history** for each symbol/period in MT5 —
   the live collector capture is not evidence of tester-history coverage.
