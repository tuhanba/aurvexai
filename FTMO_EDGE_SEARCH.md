# FTMO edge search — intraday setups (ORB, Bollinger fade)

Self-contained research (engine untouched). Round-trip cost 0.030%, FTMO 2-step, risk 0.5%, 1000 MC runs. `folds` = positive-expectancy in N of 5 contiguous OOS periods (temporal stability — the real filter).

| strategy | instrument | trades | expectancy_R | OOS folds+ | FTMO pass | survival |
|---|---|---:|---:|---:|---:|---:|
| ORB | XAUUSD | 610 | +0.138 | 4/5 | 40.6% | 98.6% |
| ORB | XAGUSD | 610 | +0.087 | 3/5 | 26.6% | 97.5% |
| BFADE | NAS100 | 198 | -0.061 | 3/5 | 9.4% | 77.5% |
| ORB | NAS100 | 545 | +0.005 | 3/5 | 0.0% | 100.0% |
| BFADE | US500 | 188 | -0.109 | 2/5 | 7.3% | 64.8% |
| ORB | USDJPY | 725 | -0.035 | 2/5 | 4.6% | 86.3% |
| ORB | GER40 | 670 | +0.003 | 2/5 | 1.0% | 99.9% |
| ORB | US30 | 538 | -0.020 | 2/5 | 0.0% | 100.0% |
| ORB | US500 | 591 | -0.035 | 2/5 | 0.0% | 99.9% |
| BFADE | GER40 | 252 | -0.064 | 1/5 | 8.4% | 74.0% |
| BFADE | XAGUSD | 551 | -0.136 | 1/5 | 3.2% | 58.0% |
| ORB | AUDUSD | 722 | -0.112 | 1/5 | 3.0% | 70.4% |
| BFADE | XAUUSD | 556 | -0.160 | 0/5 | 3.6% | 52.1% |
| BFADE | GBPUSD | 693 | -0.296 | 0/5 | 0.7% | 21.3% |
| BFADE | AUDUSD | 724 | -0.276 | 0/5 | 0.5% | 27.9% |
| BFADE | EURUSD | 702 | -0.355 | 0/5 | 0.4% | 13.1% |
| BFADE | USDJPY | 683 | -0.378 | 0/5 | 0.3% | 10.0% |
| BFADE | US30 | 203 | -0.315 | 0/5 | 0.2% | 17.9% |
| ORB | GBPUSD | 727 | -0.295 | 0/5 | 0.0% | 21.7% |
| ORB | EURUSD | 725 | -0.389 | 0/5 | 0.0% | 8.0% |

## Verdict

**Candidate found:** ORB on XAUUSD is positive in 4/5 OOS folds (exp +0.138, FTMO pass 41%). Worth deeper validation.

## Caveats

- Simplified fills (intrabar stop-before-target), flat cost, Yahoo proxy feeds, no session-time calibration per instrument.
- A stable candidate here would then be wired as a real strategy profile and validated in the full backtester under governance.
- Reproduce: `python scripts/ftmo_edge_search.py`.
