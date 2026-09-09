#!/usr/bin/env python3
"""FTMO trend-following BASKET — aggregate pass/survival on a diversified set.

The deepen study showed trend-following holds up (gold) while FX mean-reversion
does not, but a single daily instrument is too low-frequency for a challenge.
This runs `donchian_trend` as a PORTFOLIO across a diversified trending basket
(metals + indices + JPY crosses) on ONE shared FTMO account — the backtester's
native multi-symbol mode — so trade frequency is challenge-viable, and measures:

  * real portfolio backtest (net %, trades, cadence, max DD)
  * a single HISTORICAL FTMO outcome (replay the realised trade stream through
    the daily/overall floors by CE(S)T day)
  * a Monte-Carlo pass/survival distribution at the REAL trade cadence

Two configs: a 4h basket (resampled from cached 1h) and a daily basket (10y).
Writes FTMO_BASKET.md. Fetches missing instruments on first run.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester, resample
from aurvex.ftmo import ftmo_calendar as cal
from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.data import load_or_fetch
from aurvex.ftmo.ftmo_sim import monte_carlo, r_samples_from_trades
from aurvex.ftmo.rules import ruleset_for

RUNS = int(os.environ.get("FTMO_BASKET_RUNS", "3000"))
RISKS = [0.25, 0.5, 0.75]
RULESET = ruleset_for("two_step", "challenge", account_size=100_000)

# Diversified TRENDING basket: metals + indices + JPY crosses (JPY pairs trend).
BASKET_4H = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40",
             "USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY"]
BASKET_1D = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40"]


def base_cfg(ltf, htf):
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    c.risk_pct = 0.5
    c.strategy_profile = "donchian_trend"
    c.max_open_trades = 6          # a real portfolio holds several trends at once
    c.ltf, c.htf = ltf, htf
    return c


def _load(names, interval, range_):
    out = {}
    for n in names:
        try:
            c = load_or_fetch(n, interval=interval, range_=range_)
        except Exception as exc:
            print(f"    {n}: fetch failed ({exc})")
            continue
        if len(c) >= 250:
            out[n] = c
    return out


def _cadence_per_day(closed):
    ts = [t.open_time for t in closed if getattr(t, "open_time", 0)]
    if len(ts) < 2:
        return 1.0
    span_days = max(1.0, (max(ts) - min(ts)) / 86_400_000.0)
    return max(0.1, len(closed) / span_days)


def historical_outcome(closed, ruleset, initial=100_000.0):
    """Replay the realised trade stream chronologically through the FTMO floors.

    One historical path (realised PnL only — no intraday floating), so it is a
    lower bound on breaches. Returns (outcome, final_balance, max_dd_pct)."""
    st = FtmoAccountState.initial(ruleset.with_overrides(account_size=initial),
                                  starting_balance=initial,
                                  now_ms=min((t.close_time or t.open_time)
                                             for t in closed) if closed else None)
    bal = initial
    peak = initial
    max_dd = 0.0
    for t in sorted(closed, key=lambda x: (x.close_time or x.open_time)):
        ts = t.close_time or t.open_time
        st.update(balance=bal, equity=bal, now_ms=ts)   # rolls CE(S)T days
        bal += (t.realized_pnl or 0.0)
        st.update(balance=bal, equity=bal, now_ms=ts)
        peak = max(peak, bal)
        max_dd = max(max_dd, peak - bal)
        if st.daily_breached:
            return "breach_daily", bal, 100 * max_dd / initial
        if st.max_loss_breached:
            return "breach_max", bal, 100 * max_dd / initial
    passed = (bal - initial) >= ruleset.profit_target_amount()
    return ("pass" if passed else "no_target_yet"), bal, 100 * max_dd / initial


def run_basket(label, cfg, data):
    if not data:
        print(f"  {label}: no data")
        return None
    bt = Backtester(cfg)
    m = bt.run(data)
    closed = getattr(bt, "_last_closed", []) or []
    r = r_samples_from_trades(closed)
    cadence = _cadence_per_day(closed)
    tpd = max(1, round(cadence))
    print(f"  {label}: instruments={len(data)} trades={len(closed)} "
          f"net={m.get('return_pct')}% exp={m.get('expectancy_r')} "
          f"cadence={cadence:.2f}/day")
    row = {"label": label, "instruments": len(data), "trades": len(closed),
           "net_pct": m.get("return_pct"), "exp": m.get("expectancy_r"),
           "cadence": round(cadence, 2), "risk": {}, "hist": None}
    if closed:
        outcome, final_bal, dd = historical_outcome(closed, RULESET)
        row["hist"] = (outcome, round(final_bal, 0), round(dd, 1))
        print(f"       historical path: {outcome}  final={final_bal:,.0f}  maxDD={dd:.1f}%")
    if len(r) >= 30:
        for risk in RISKS:
            rep = monte_carlo(r, RULESET, n_runs=RUNS, risk_pct=risk,
                              trades_per_day=tpd, max_days=90)
            row["risk"][risk] = (rep.pass_rate, rep.survival_rate,
                                 rep.avg_max_drawdown_pct)
            print(f"       risk {risk}%  pass={rep.pass_rate*100:5.1f}%  "
                  f"survival={rep.survival_rate*100:5.1f}%  dd={rep.avg_max_drawdown_pct}%")
    return row


def main():
    rows = []

    print("4h basket (resampled from cached 1h)…")
    raw_1h = _load(BASKET_4H, "1h", "730d")
    data_4h = {k: resample(v, "1h", "4h") for k, v in raw_1h.items()}
    rows.append(run_basket("donchian 4h/1d BASKET",
                           base_cfg("4h", "1d"), data_4h))

    print("daily basket (10y)…")
    data_1d = _load(BASKET_1D, "1d", "10y")
    rows.append(run_basket("donchian 1d/30d BASKET",
                           base_cfg("1d", "30d"), data_1d))

    lines = ["# FTMO trend-following basket — aggregate pass/survival", "",
             f"`donchian_trend` portfolio (max 6 concurrent), {RUNS} Monte-Carlo "
             "runs at the real trade cadence, 2-step challenge, 90-day horizon, "
             "FTMO 100k.", "",
             "| basket | instruments | trades | net % | expectancy_R | cadence/day "
             "| historical path | risk | FTMO pass | survival |",
             "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|"]
    for r in rows:
        if not r:
            continue
        hist = f"{r['hist'][0]} (dd {r['hist'][2]}%)" if r["hist"] else "—"
        if not r["risk"]:
            lines.append(f"| {r['label']} | {r['instruments']} | {r['trades']} | "
                         f"{r['net_pct']}% | {r['exp']} | {r['cadence']} | {hist} "
                         f"| — | — | — |")
            continue
        first = True
        for risk, (pr, sr, dd) in r["risk"].items():
            if first:
                lines.append(f"| {r['label']} | {r['instruments']} | {r['trades']} "
                             f"| {r['net_pct']}% | {r['exp']} | {r['cadence']} | "
                             f"{hist} | {risk}% | {pr*100:.1f}% | {sr*100:.1f}% |")
                first = False
            else:
                lines.append(f"| | | | | | | | {risk}% | {pr*100:.1f}% | {sr*100:.1f}% |")
    lines += ["", "## Notes", "",
              "- Portfolio = one shared FTMO account, up to 6 concurrent trend "
              "trades across the basket (the backtester's native multi-symbol "
              "mode), so the cadence is aggregate and challenge-viable.",
              "- 'historical path' replays the realised trade stream through the "
              "daily/overall floors by CE(S)T day (realised only, no intraday "
              "floating → a lower bound on breaches). Monte-Carlo adds the "
              "distribution at the real cadence.",
              "- Still in-sample, crypto cost model, Yahoo proxy feeds. Walk-"
              "forward + real FX/CFD costs are the next gate before any funded use.",
              "- Reproduce: `python scripts/ftmo_basket.py`.", ""]
    with open("FTMO_BASKET.md", "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print("\nwrote FTMO_BASKET.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
