# FTMO optimization frontier — exhaustive lever test (2026-08-06)

A deliberate "leave no stone unturned" pass over every structural lever, each on
5 contiguous out-of-sample folds (~2.5y of 1h data, no fitted params → temporal
stability). The goal was to find anything that raises the profitability rate
without added risk. The honest result: **the system is already at its optimum on
every structural dimension** — the only real wins were an added edge (JP225) and
risk timing (challenge-mode), both already applied.

| lever tested | variants | verdict |
|---|---|---|
| **New instruments** | 12 candidates | Only **JP225** survives OOS; rest overfit (WTI failed 3/5) |
| **Per-trade risk** | 0.5–2.0% | **0.5% is the safe ceiling**; 1.0% for challenge only (bounded downside) |
| **ORB session hour** | 0,1,7,8,12,13,14 UTC | **hour 0 best** (0.245R); London/NY negative |
| **ORB range length** | 1h,2h,3h,4h | **1h best** (0.245R); longer ~0.10R |
| **Exit / take-profit** | session-close vs 1R/1.5R/2R/3R | **session-close best**; every fixed TP worse (caps the runners) |
| **Breakeven stop** | none vs BE@1R/1.5R/2R | **no help** (0.369 vs ≤0.366); BE cuts winners that dip then run |
| **HTF trend filter** | 50h MA-aligned breakouts | **no help once look-ahead removed** (see below) |

## The trend-filter look-ahead catch (why we re-test)

A first pass showed the trend filter lifting expectancy 0.369R → 0.560R across all
five folds — a spectacular, robust-looking result. On review it was a **look-ahead
artifact**: the filter used the breakout bar's *close* to decide entry, but a
stop-entry fills *intrabar*, before that close is known. Re-running with the trend
known strictly before the bar (entry level vs prior-bar MA50) erased the gain
(0.353R, marginally worse). This is exactly the bug that makes a system look great
in backtest and fail live — caught by skepticism and a rigorous re-test, not taken
as a win.

## Conclusion

Every structural tweak either confirms the current choice is optimal or turns out
to be noise / an artifact. A system where nothing you try improves it is a system
already at its optimum — the intended outcome of exhaustive testing. Remaining
speed comes from **execution, not parameters**: proven edge (4 validated setups),
challenge-mode risk to pass fast, 24/5 uptime (no missed setups), post-funded
capital scaling to $400k, and discipline (no manual overrides, no risk-cranking).
The frontier is now live data (KAPI 1), not more backtesting.
