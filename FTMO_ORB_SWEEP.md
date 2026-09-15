# ORB-on-gold parameter sweep

Round-trip cost 0.030%, FTMO 2-step, risk 0.5%, 1000 MC runs. Ranked by OOS fold-consistency, then FTMO pass, then expectancy. `tgt=close` = exit at session close.

| instrument | session | orb hrs | target | trades | expectancy_R | OOS folds+ | FTMO pass | survival |
|---|---|---:|---|---:|---:|---:|---:|---:|
| XAGUSD | UTCday | 1 | close | 614 | +0.414 | 5/5 | 76.7% | 87.5% |
| XAUUSD | UTCday | 1 | 3.0 | 614 | +0.196 | 5/5 | 54.8% | 96.0% |
| XAGUSD | UTCday | 2 | close | 609 | +0.098 | 5/5 | 35.0% | 90.0% |
| XAUUSD | UTCday | 2 | 2.0 | 611 | +0.112 | 5/5 | 31.5% | 97.5% |
| XAGUSD | UTCday | 2 | 3.0 | 609 | +0.077 | 5/5 | 26.2% | 94.2% |
| XAUUSD | UTCday | 2 | 1.5 | 611 | +0.075 | 5/5 | 18.4% | 97.8% |
| XAGUSD | UTCday | 4 | 1.5 | 592 | +0.057 | 5/5 | 11.9% | 98.6% |
| XAUUSD | UTCday | 1 | close | 614 | +0.342 | 4/5 | 71.1% | 86.7% |
| XAUUSD | UTCday | 4 | close | 597 | +0.141 | 4/5 | 45.3% | 96.5% |
| XAUUSD | UTCday | 3 | close | 604 | +0.147 | 4/5 | 44.0% | 95.2% |
| XAUUSD | UTCday | 2 | close | 611 | +0.146 | 4/5 | 43.0% | 93.9% |
| XAUUSD | NY | 1 | close | 734 | +0.078 | 4/5 | 34.3% | 91.0% |
| XAUUSD | UTCday | 4 | 3.0 | 597 | +0.109 | 4/5 | 33.0% | 97.4% |
| XAUUSD | UTCday | 3 | 3.0 | 604 | +0.106 | 4/5 | 32.7% | 96.6% |
| XAUUSD | UTCday | 2 | 3.0 | 611 | +0.096 | 4/5 | 31.0% | 93.8% |
| XAUUSD | UTCday | 1 | 2.0 | 614 | +0.104 | 4/5 | 30.8% | 95.3% |
| XAGUSD | NY | 1 | close | 735 | +0.056 | 4/5 | 26.7% | 92.9% |
| XAGUSD | UTCday | 3 | close | 599 | +0.062 | 4/5 | 25.8% | 92.4% |
| XAUUSD | UTCday | 4 | 2.0 | 597 | +0.085 | 4/5 | 23.6% | 98.8% |
| XAUUSD | UTCday | 4 | 1.5 | 597 | +0.097 | 4/5 | 22.2% | 99.5% |

## Verdict

**Strong operating point:** XAGUSD UTCday orb=1h tgt=close → 5/5 folds, FTMO pass 77%. Candidate to wire + validate in the full backtester under governance.

*Caveats: simplified fills, flat cost, Yahoo proxy. Reproduce: `python scripts/ftmo_orb_sweep.py`.*
