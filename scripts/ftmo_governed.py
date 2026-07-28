#!/usr/bin/env python3
"""Governance-in-the-loop test: does the FTMO risk engine keep drawdown < 10%?

For each config, run the SAME trend strategy twice:
  * RAW      — FTMO_MODE off; replay the realised trade stream through the FTMO
               floors to get the historical breach / max drawdown.
  * GOVERNED — FTMO_MODE on inside the backtester: the compliance gate blocks
               worst-case-breaching entries, health/mode down-size risk as the
               account weakens, and Survival halts new risk. Reports the governed
               breach / max drawdown / pass.

If governance works, the −20% breach of the raw daily basket should become a
survivable (<10% DD), non-breaching path. Writes FTMO_GOVERNED.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester, resample
from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.data import load_or_fetch
from aurvex.ftmo.ftmo_sim import r_samples_from_trades
from aurvex.ftmo.rules import ruleset_for

RULESET = ruleset_for("two_step", "challenge", account_size=100_000)
BASKET_4H = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40",
             "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY"]
BASKET_1D = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40"]


def cfg(ltf, htf, governed, max_open=6):
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    c.risk_pct = 0.5
    c.strategy_profile = "donchian_trend"
    c.max_open_trades = max_open
    c.ltf, c.htf = ltf, htf
    c.ftmo_mode_enabled = governed
    return c


def raw_historical(closed, initial=100_000.0):
    """Replay realised trades through the FTMO floors (raw, realised-only)."""
    if not closed:
        return "no_trades", 0.0
    rs = RULESET.with_overrides(account_size=initial)
    st = FtmoAccountState.initial(rs, starting_balance=initial,
                                  now_ms=min((t.close_time or t.open_time)
                                             for t in closed))
    bal = initial
    peak = initial
    mdd = 0.0
    for t in sorted(closed, key=lambda x: (x.close_time or x.open_time)):
        ts = t.close_time or t.open_time
        st.update(balance=bal, equity=bal, now_ms=ts)
        bal += (t.realized_pnl or 0.0)
        st.update(balance=bal, equity=bal, now_ms=ts)
        peak = max(peak, bal)
        mdd = max(mdd, peak - bal)
        if st.daily_breached:
            return "breach_daily", 100 * mdd / initial
        if st.max_loss_breached:
            return "breach_max", 100 * mdd / initial
    passed = (bal - initial) >= rs.profit_target_amount()
    return ("pass" if passed else "survived_no_target"), 100 * mdd / initial


def load(names, interval, range_):
    out = {}
    for n in names:
        try:
            c = load_or_fetch(n, interval=interval, range_=range_)
        except Exception:
            continue
        if len(c) >= 250:
            out[n] = c
    return out


def run(label, ltf, htf, data, max_open=6):
    if not data:
        print(f"  {label}: no data")
        return None
    # RAW
    btr = Backtester(cfg(ltf, htf, governed=False, max_open=max_open))
    mr = btr.run(data)
    raw_closed = getattr(btr, "_last_closed", []) or []
    raw_outcome, raw_dd = raw_historical(raw_closed)
    # GOVERNED
    btg = Backtester(cfg(ltf, htf, governed=True, max_open=max_open))
    mg = btg.run(data)
    g = mg.get("ftmo_governed", {})
    g_closed = getattr(btg, "_last_closed", []) or []
    print(f"  {label}")
    print(f"    RAW      trades={len(raw_closed):4d} net={mr.get('return_pct')}% "
          f"-> {raw_outcome}  maxDD={raw_dd:.1f}%")
    print(f"    GOVERNED trades={len(g_closed):4d} net={mg.get('return_pct')}% "
          f"-> breach={g.get('breach')} maxDD={g.get('max_drawdown_pct')}% "
          f"passed={g.get('passed')} mode_end={g.get('mode_end')}")
    return {"label": label, "raw": (len(raw_closed), mr.get("return_pct"),
                                    raw_outcome, round(raw_dd, 1)),
            "gov": (len(g_closed), mg.get("return_pct"), g.get("breach"),
                    g.get("max_drawdown_pct"), g.get("passed"),
                    g.get("mode_end"))}


def main():
    rows = []
    print("Loading data …")
    gold_1d = load(["XAUUSD"], "1d", "10y")
    basket_1d = load(BASKET_1D, "1d", "10y")
    raw_1h = load(BASKET_4H, "1h", "730d")
    basket_4h = {k: resample(v, "1h", "4h") for k, v in raw_1h.items()}

    rows.append(run("GOLD daily 1d/30d", "1d", "30d", gold_1d, max_open=1))
    rows.append(run("BASKET daily 1d/30d", "1d", "30d", basket_1d, max_open=6))
    rows.append(run("BASKET 4h/1d", "4h", "1d", basket_4h, max_open=6))

    lines = ["# FTMO governance-in-the-loop — RAW vs GOVERNED", "",
             "Same donchian trend strategy, run twice: RAW (no FTMO throttle, "
             "realised-path replay through the floors) vs GOVERNED (compliance "
             "gate + health/mode sizing + Survival halt live in the backtester). "
             "2-step challenge, FTMO 100k, risk 0.5%.", "",
             "| config | RAW trades | RAW net | RAW outcome | RAW maxDD | "
             "GOV trades | GOV net | GOV breach | GOV maxDD | GOV passed |",
             "|---|---:|---:|---|---:|---:|---:|---|---:|---:|"]
    for r in rows:
        if not r:
            continue
        rt, rn, ro, rd = r["raw"]
        gt, gn, gb, gd, gp, gm = r["gov"]
        lines.append(f"| {r['label']} | {rt} | {rn}% | {ro} | {rd}% | "
                     f"{gt} | {gn}% | {gb or 'none'} | {gd}% | {gp} |")
    lines += ["", "## Reading it", "",
              "- **RAW maxDD** is what the strategy does unthrottled; **GOV maxDD** "
              "is with the FTMO risk engine live. Governance succeeds if it turns "
              "a RAW breach into a GOV non-breach with maxDD < 10%.",
              "- GOVERNED down-sizes via health and blocks worst-case-breaching "
              "entries, so it trades less and grows slower — the trade-off for "
              "staying inside the envelope.",
              "- Still in-sample, crypto cost model, Yahoo proxy. Walk-forward + "
              "real FX/CFD costs remain the go/no-go gate.",
              "- Reproduce: `python scripts/ftmo_governed.py`.", ""]
    with open("FTMO_GOVERNED.md", "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print("\nwrote FTMO_GOVERNED.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
