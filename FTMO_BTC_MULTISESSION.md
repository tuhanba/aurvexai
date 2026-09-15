# BTC multi-session ORB — a validated speed lever (2026-09-08)

Research into "we don't have to be slow": can the core instruments support MORE
than one ORB session per day, multiplying trade count (faster compounding) at no
added per-trade risk?

## Method
24-hour ORB range-hour sweep on the 24h-tradeable core (gold, silver, BTC),
honest live-real fills, then a long-vs-short symmetry test to separate a real
intraday edge from bull-trend contamination (a long-biased crypto book profits
from the 2024-26 uptrend regardless of any real edge).

## Result

- **Gold / silver: single session only.** The positive hours (00-04 UTC) are the
  same Asian-session breakout captured with adjacent range hours, not independent
  sessions. No stackable second session.
- **BTC: multiple genuine sessions.** ORB is positive and OOS-stable at several
  hours. The symmetry test confirms hours **00, 03 and 13 UTC are trend-neutral**
  — long AND short both positive even at a realistic 0.10% crypto cost:

  | hour | LONG @0.10% | SHORT @0.10% | verdict |
  |---:|---:|---:|---|
  | 03 | +0.176 | +0.199 | real (symmetric) |
  | 13 | +0.046 | +0.072 | real (small) |
  | 07 | +0.694 | +0.023 | long-biased (trend, do not trust magnitude) |
  | 08 | +0.247 | +0.007 | long-biased |

  Hours 07/08 look spectacular but are long-dominated — bull-trend riding, not a
  repeatable edge. Hours 0/3/13 are the trustworthy, symmetric ones.

## The lever

BTC can run **2-3 ORB sessions per day** (00, 03, 13 UTC) with genuine
trend-neutral edge, ~2-3x the BTC trade count → faster compounding, no added
per-trade risk. Metals cannot (one session).

## Caveats before implementing

1. **EA work required** — the EA arms one ORB per day per chart; multi-session
   needs independent ORB arming at each session hour on the BTC chart.
2. **BTC concentration** — 3 same-day BTC sessions are correlated (same asset),
   so the TOTAL daily BTC risk must be capped (e.g., 3 x 0.10% = 0.30% total,
   not 3 x the per-trade %). Otherwise a trending-down BTC day loses on all three.
3. **Crypto spread unconfirmed live** — the edge shrinks from 0.04% to 0.10%
   cost; the real FTMO crypto spread (KAPI-1) is the arbiter.

## Disciplined sequence

Do NOT build multi-session complexity on an unproven live foundation. Order:
1. Launch $25k with BTC **single-session** (already in the core config).
2. KAPI-1: confirm BTC's live single-session edge and real spread.
3. Only then add BTC **multi-session** (00/03/13 UTC) with a capped total BTC
   risk — the validated speed lever, switched on once the live foundation holds.

Reproduce: the 24-hour sweep + long/short symmetry test build on
`scripts/ftmo_trail_probe.py`.
