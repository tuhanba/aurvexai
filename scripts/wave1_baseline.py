#!/usr/bin/env python3
"""
Wave 1 baseline report generator (T7).

Runs the deterministic offline backtest through the REPAIRED engine (closed
candles, no lookahead, cost-inclusive sizing, slot-aware leverage) with
realistic fees/slippage, and writes WAVE1_BASELINE.md.

Wave 2 exit/TA experiments must be compared against THIS baseline, never the
contaminated legacy history. Deterministic: fixed symbols/window/seed, so the
report reproduces exactly.

Run (one line, no &&):
    python scripts/wave1_baseline.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.backtest import run_backtest_offline  # noqa: E402
from aurvex.config import Config  # noqa: E402

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
BARS = 3000          # 1m bars per symbol (~50h each), deterministic
SEED = 20240601
OUT = os.path.join(os.path.dirname(__file__), "..", "WAVE1_BASELINE.md")


def _fmt_pf(m):
    pf = m.get("profit_factor")
    return "inf" if pf is None else f"{pf:.3f}"


def build_report(m: dict) -> str:
    start = m["start_balance"]
    end = m["end_balance"]
    dd_usdt = m["max_drawdown"]
    dd_pct = round(dd_usdt / start * 100, 3) if start else 0.0
    lev = ", ".join(f"{k}x×{v}" for k, v in m.get("leverage_dist", {}).items()) or "—"
    rej = "\n".join(f"  - {k}: {v}" for k, v in m.get("reject_reasons", {}).items()) or "  - none"
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""# Wave 1 baseline (deterministic backtest)

Generated: {now}
Generator: `scripts/wave1_baseline.py` · symbols={SYMBOLS} · bars/symbol={BARS} · seed={SEED}

This is the post-Wave-1 baseline through the repaired engine (closed-candle
discipline, entry-bar/one-fill timing, cost-inclusive sizing, slot-aware
leverage), net of fees + assumed slippage. **Wave 2 compares against this, not
the legacy history.** `READY_FOR_PAPER: YES` is gated on this report; live stays
OFF.

## Net edge
| metric | value |
|---|---|
| start balance | {start:.2f} USDT |
| end balance | {end:.2f} USDT |
| return | {m['return_pct']:.3f} % |
| net PnL | {m['net_pnl']:.4f} USDT |
| expectancy / trade | {m['expectancy']:.4f} USDT ({m['expectancy_r']:+.3f} R) |
| avg net R | {m['avg_r']:+.4f} |
| profit factor | {_fmt_pf(m)} |
| winrate | {m['winrate']:.2f} % |
| max drawdown | {dd_usdt:.4f} USDT ({dd_pct:.3f} %) |

## Activity
| metric | value |
|---|---|
| signals seen | {m['signals_seen']} |
| allows | {m['allows']} |
| total trades | {m['total_trades']} |
| trades / day | {m.get('trades_per_day', 0.0)} |
| margin-rejected signals | {m.get('margin_rejected_signals', 0)} |

## TP ladder (how far winners ran)
| step | count | transition |
|---|---|---|
| TP1 | {m.get('tp1_hits', 0)} | — |
| TP2 | {m.get('tp2_hits', 0)} | TP1→TP2 {m.get('tp1_to_tp2_rate', 0.0)} % |
| TP3 | {m.get('tp3_hits', 0)} | TP2→TP3 {m.get('tp2_to_tp3_rate', 0.0)} % |
| SL closes | {m.get('sl_closes', 0)} | BE closes {m.get('be_closes', 0)} |

## Cost & margin
| metric | value |
|---|---|
| total fees | {m.get('fees_total', 0.0)} USDT |
| fee share of turnover | {m.get('fee_share_of_turnover_pct', 0.0)} % |
| avg margin used | {m.get('avg_margin_used', 0.0)} USDT |
| max margin used | {m.get('max_margin_used', 0.0)} USDT |
| leverage distribution | {lev} |

## Reject reasons
{rej}

## Deferred to Wave 2
- Per-trade MAE/MFE excursion (`mae_mfe = {m.get('mae_mfe')}`) — needs per-bar
  excursion capture in the replay harness.

---
_Raw metrics JSON below for tooling._

```json
{json.dumps(m, indent=2, default=str)}
```
"""


def main() -> None:
    cfg = Config()
    cfg.initial_paper_balance = 1000.0
    cfg.data_provider = "synthetic"
    m = run_backtest_offline(cfg, symbols=SYMBOLS, bars=BARS, seed=SEED)
    report = build_report(m)
    with open(OUT, "w") as fh:
        fh.write(report)
    print(f"wrote {os.path.relpath(OUT)}")
    print(f"  trades={m['total_trades']} return={m['return_pct']}% "
          f"avgR={m['avg_r']:+.3f} PF={_fmt_pf(m)} "
          f"maxDD={m['max_drawdown']:.2f} margin_rejects={m.get('margin_rejected_signals', 0)}")


if __name__ == "__main__":
    main()
