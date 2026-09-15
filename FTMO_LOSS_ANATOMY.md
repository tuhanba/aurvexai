# Loss anatomy — why we lose, why we don't make more (2026-09-08)

Decomposition of the core edge (gold + silver + BTC ORB, 1593 honest trades) to
answer directly: where do we lose, why, and why don't we make more?

## The edge is starkly bimodal

| category | trades | % | total R |
|---|---:|---:|---:|
| STOP (full loss, R<−0.8) | 1156 | 73% | −1310 |
| small loss (−0.8..0) | 42 | 3% | −13 |
| small win (0..1R) | 76 | 5% | +39 |
| BIG WIN (≥1R) | 319 | 20% | +1557 |

Expectancy +0.172R, win rate 25%. Losers average −1.10R; winners average +4.04R;
the top 10% of winners make 33% of all profit.

## Direct answers

- **Where do we lose?** Entirely in the stop-outs — 73% of breakouts fail and
  reverse to the −1R stop. The middle (small win/loss) is negligible.
- **Why do we lose?** Because most breakouts are false. That is the *nature* of
  breakout trading, not a defect — no tested filter reduces the 73% failure rate.
- **Why don't we make more?** Win rate is only 25%; even though winners are big
  (+4R), the 73% stop rate pulls the average to +0.17R. Profit depends on
  catching the rare huge runner (fat tail).

## What would raise it — and what was tested & rejected

Only a filter that lowers the false-breakout rate *without* cutting winners would
help. None found:

- **Momentum filter** (prior-bar direction): does not predict which breakouts
  succeed — win rate stays 25%, expectancy unchanged/slightly worse. Rejected.
- **Fibonacci targets** (1.0/1.618/2.618× range): every variant NEGATIVE
  (−0.19 / −0.11 / −0.04) — a Fib target is just a fixed take-profit that caps
  the fat tail (win rate rises to 47% but total R goes negative). Fibonacci is
  not a magic tool. Rejected — same result as all fixed TPs, trailing, stall,
  peak-R exits.

## Conclusion

The edge is structurally fixed: ~73% false breakouts (irreducible with our
tools), ~20% big winners (the fat tail that pays). Nothing reduces the loss rate
robustly. The only ways to make more, all applied: more real-edge instruments
(BTC + multi-session), capital scaling, and the discipline to hold winners to
session close. "Full automation" already exists — the EA runs the entire loop.
