# Signal & exit experiments — four fresh cost-honest tests (2026-07-20)

Owner questions: "there are tons of TA — why only 5 legs?", "can you create your
own winning TA?", "what about Fibonacci?", plus the BE-stop offered earlier. All
four run through the SAME cost-honest frame: signal on a CLOSED bar, enter next,
hold H, net of 0.13% round-trip, expressed as R vs a 2×ATR stop, pooled across
11 coins on 4h. Scripts: `classic_ta_battery.py`, `cross_sectional_test.py`,
`fib_test.py`, `be_stop_backtest.py`.

## 1. Classic-TA battery — 14 textbook indicators

| family | representative result | verdict |
|---|---|---|
| Oscillators / mean-reversion (RSI, Stoch, CCI, Williams%R, Bollinger-z) | −0.06 to −0.10R, t −10 to −17 | reliably LOSE |
| Momentum (RSI>50, MACD, ROC, Stoch-mom, EMA cross) | −0.005 to +0.008R, t ~0 | near zero |
| Trend / breakout (Donchian, ADX+DI, EMA9/21) | 0 to +0.009R, t < 3 | best, still sub-GO raw |

Two structural truths: (a) oscillators are not untested gold, they are proven
money-losers after cost; (b) the six "different" momentum indicators all cluster
at the same near-zero value because they are ONE idea (price momentum) in
different clothes — "tons of TA" is mostly correlated repackaging, ~5 independent
ideas. Only trend/breakout clears zero, and raw Donchian is only +0.009R (no-go)
while the deployed `donchian_trend` is +0.28R — the gap is REFINEMENT (entry
filter + exit + runner harvesting), not a different indicator.

## 2. Cross-sectional relative-strength (a genuinely new axis)

Market-neutral long-strongest / short-weakest, rebalanced — structurally unlike
single-asset TA, and not covered by the 215-trial base. Result: **NO-GO**.
Momentum sign is −0.04 to −0.46% per hold (gross signal is real — reversal is
strongly negative, so winners do keep winning — but the edge is sub-cost);
short-term reversal is −0.6 to −1.0% per hold (t −3 to −8). The cost wall again.

## 3. Fibonacci retracement — NO-GO, and worse the "purer" it gets

| level | net Exp-R (24/6) | t |
|---|---|---|
| 0.382 | −0.004 … +0.017 | ~0–2 |
| 0.500 | −0.033 | −5.5 |
| 0.618 (golden) | −0.063 | −9.4 |
| 0.786 | −0.089 | −9.7 |

The deeper, more "textbook" the retracement, the more reliably it LOSES. The one
marginally-positive cell (shallow 0.382) is just momentum wearing a fib costume —
a shallow pullback in an uptrend is "still trending." The market does not respect
fib levels; a deep retrace more often precedes continuation of the reversal.

## 4. Breakeven-stop — proper backtest OVERTURNS the earlier estimate

An earlier quick reconstruction (peak-R over the window, converting only losers)
looked +21%. The **proper sequenced** backtest — arm BE once favorable excursion
≥ ARM×R, then exit at breakeven if price returns to entry, in bar order —
captures the WINNER-CUT cost the estimate missed:

| ARM×R | HOLD Exp-R | BE Exp-R | Δ | MaxDD |
|---|---|---|---|---|
| 1.0 | +0.176 | +0.146 | **−17%** | 26→25% |
| 1.5 | +0.176 | +0.164 | −7% | 26→27% |
| 2.0 | +0.176 | +0.163 | −7% | 26→27% |

**BE-stop is expectancy-NEGATIVE and does not cut drawdown — NOT shipped.** Same
lesson as the lookahead catch: a quick estimate that looks good is a hypothesis
to be killed by a proper test, not shipped. Trades that arm BE at +1R then dip
back through entry are exactly the ones that would have recovered to big runner
winners; cutting them truncates the positive-skew tail that IS the edge.

## The through-line

Every entry experiment (14 classics + cross-sectional + Fibonacci, on top of the
215-trial base + ML feature-combo) is NO-GO after cost, because gross edge on
retail OHLCV is ≈ +0.05–0.08R and cost is 0.2–0.6R at these stops. Every exit
experiment that *caps* (TP ladder, BE-stop, a tight daily flatten) HURTS, because
the book is positive-skew and the tail is the edge. The only exit-side wins are
the ones that LET WINNERS RUN and protect give-back WITHOUT capping runners — the
mechanism exits and the daily giveback guard (which only fires after a peak fades
and never touches a still-running day). New *entry* edge needs different DATA
(L2/order-flow/tick, on-chain), not another price/volume formula.
