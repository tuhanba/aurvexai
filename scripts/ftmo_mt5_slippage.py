#!/usr/bin/env python3
"""Auto GO/NO-GO from a raw MT5 history export — no manual data entry.

KAPI 1: does the edge survive REAL fills? The EA sizes every trade to risk
exactly RISK_PCT of the account, so each trade's realised R = profit / risk_usd,
and that profit already bakes in every real cost (spread + entry/exit slippage +
commission + swap). So the realised expectancy in R IS the live-adjusted edge —
no need to match intended levels.

Feed it the file MT5 produces from the **History** tab -> right-click ->
"Rapor / Report" (save the HTML), or a CSV. Turkish and English column headers
are both understood. It maps broker symbols (GER40.cash, US100.cash, JP225.cash,
XAUUSD) to the friendly instruments, computes realised expectancy per instrument
and overall, and compares to the backtest edge (~0.20R) for a concrete verdict.

Run:  python scripts/ftmo_mt5_slippage.py path/to/mt5_report.html
Env:  FTMO_ACCOUNT_SIZE (default 100000), FTMO_RISK_PCT (default 0.5)
No file -> a tiny SYNTHETIC report is parsed so you can see the output shape.
"""
import os
import re
import sys
from html.parser import HTMLParser

ACCOUNT = float(os.environ.get("FTMO_ACCOUNT_SIZE", "100000"))
RISK_PCT = float(os.environ.get("FTMO_RISK_PCT", "0.5"))
RISK_USD = ACCOUNT * RISK_PCT / 100.0
BACKTEST_EXP = 0.20          # validated portfolio expectancy in R
GO_MIN_EXP = 0.10            # realised expectancy must clear this (half the edge)

# broker symbol prefix -> friendly instrument
SYMBOL_MAP = [("XAU", "XAUUSD"), ("XAG", "XAGUSD"), ("GER40", "GER40"),
              ("DE40", "GER40"), ("US100", "NAS100"), ("NAS100", "NAS100"),
              ("USTEC", "NAS100"), ("JP225", "JP225"), ("JPN225", "JP225"),
              ("US30", "US30"), ("US500", "US500"), ("SPX", "US500")]

# header tokens (lowercased) we look for, EN + TR
H_SYMBOL = {"symbol", "sembol"}
H_PROFIT = {"profit", "kâr", "kar", "net", "net kâr", "net kar"}
H_VOLUME = {"volume", "hacim", "lot", "lots"}
H_TYPE = {"type", "tür", "tur", "direction", "yön", "yon"}


def friendly(sym):
    s = (sym or "").upper()
    for pref, name in SYMBOL_MAP:
        if s.startswith(pref) or pref in s:
            return name
    return None


def to_float(s):
    """Parse a report number: strip spaces/NBSP/thousands, handle , or . decimal."""
    if s is None:
        return None
    t = str(s).replace("\xa0", " ").strip().replace(" ", "")
    if not t or t in ("-", "—"):
        return None
    if "," in t and "." in t:          # 1,234.56  -> commas are thousands
        t = t.replace(",", "")
    elif "," in t:                     # 1234,56   -> comma is decimal
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


class _Tables(HTMLParser):
    """Collect every <table> as a list of rows, each row a list of cell texts."""
    def __init__(self):
        super().__init__()
        self.tables, self._t, self._r, self._c = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = ""

    def handle_data(self, data):
        if self._c is not None:
            self._c += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None:
            self._r.append(re.sub(r"\s+", " ", self._c).strip()); self._c = None
        elif tag == "tr" and self._r is not None:
            self._t.append(self._r); self._r = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t); self._t = None


def _find_columns(rows):
    """Locate the header row and the symbol/profit/type/volume column indices."""
    for hi, row in enumerate(rows):
        low = [c.lower().strip() for c in row]
        sym_i = next((i for i, c in enumerate(low) if c in H_SYMBOL), None)
        prof_is = [i for i, c in enumerate(low) if c in H_PROFIT]
        if sym_i is not None and prof_is:
            typ_i = next((i for i, c in enumerate(low) if c in H_TYPE), None)
            vol_i = next((i for i, c in enumerate(low) if c in H_VOLUME), None)
            return hi, sym_i, prof_is[-1], typ_i, vol_i     # last profit col = net
    return None


def parse_trades_html(text):
    p = _Tables(); p.feed(text)
    trades = []
    for rows in p.tables:
        cols = _find_columns(rows)
        if not cols:
            continue
        hi, sym_i, prof_i, typ_i, vol_i = cols
        for row in rows[hi + 1:]:
            if max(sym_i, prof_i) >= len(row):
                continue
            name = friendly(row[sym_i])
            profit = to_float(row[prof_i])
            if name is None or profit is None:
                continue
            trades.append({"instr": name, "profit": profit,
                           "type": (row[typ_i] if typ_i is not None and typ_i < len(row) else ""),
                           "vol": to_float(row[vol_i]) if vol_i is not None and vol_i < len(row) else None})
    return trades


def parse_trades_csv(text):
    import csv as _csv
    rows = list(_csv.reader(text.splitlines()))
    cols = _find_columns(rows)
    if not cols:
        return []
    hi, sym_i, prof_i, typ_i, vol_i = cols
    out = []
    for row in rows[hi + 1:]:
        if max(sym_i, prof_i) >= len(row):
            continue
        name = friendly(row[sym_i]); profit = to_float(row[prof_i])
        if name and profit is not None:
            out.append({"instr": name, "profit": profit,
                        "type": row[typ_i] if typ_i is not None and typ_i < len(row) else "",
                        "vol": to_float(row[vol_i]) if vol_i is not None and vol_i < len(row) else None})
    return out


def _synthetic_report():
    """A tiny MT5-style HTML report so the tool is runnable with no file."""
    import random
    rng = random.Random(3)
    rows = ["<table><tr><th>Zaman</th><th>Sembol</th><th>Tür</th>"
            "<th>Hacim</th><th>Fiyat</th><th>Komisyon</th><th>Takas</th><th>Kâr</th></tr>"]
    def add(sym, r):
        rows.append(f"<tr><td>2026.08.0x</td><td>{sym}</td><td>buy</td>"
                    f"<td>0.50</td><td>100.0</td><td>-2.0</td><td>0.0</td>"
                    f"<td>{r*RISK_USD:.2f}</td></tr>")
    for _ in range(30):                                   # gold: ~0.18R after real cost
        add("XAUUSD", rng.choice([1.7, -1, 1.7, -1, -1, 2.4, -1, 1.7]) - 0.05)
    for _ in range(20):                                   # index: ~0.15R
        add("GER40.cash", rng.choice([1.9, -1, -1, 2.5, -1, 1.9]) - 0.05)
    rows.append("</table>")
    return "".join(rows)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FTMO_MT5_REPORT")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        trades = parse_trades_html(text) if ("<" in text[:2000]) else parse_trades_csv(text)
        src = f"{len(trades)} trades from {path}"
    else:
        trades = parse_trades_html(_synthetic_report())
        src = f"{len(trades)} SYNTHETIC trades (pass a real MT5 report for a real verdict)"

    print(f"AurvexFTMO · MT5 fill scorer · acct ${ACCOUNT:,.0f} · risk {RISK_PCT}% "
          f"(${RISK_USD:,.0f}/trade)\nloaded {src}\n")
    if not trades:
        print("No trades parsed. In MT5: History tab -> right-click -> Report -> save\n"
              "the HTML, then: python scripts/ftmo_mt5_slippage.py <that file>.")
        return 1

    by = {}
    for t in trades:
        by.setdefault(t["instr"], []).append(t["profit"])

    print(f"{'instrument':10s} {'n':>4s} {'win%':>5s} {'exp_R':>7s} {'netR':>7s} "
          f"{'net$':>10s} {'net%':>7s}")
    tot_R = tot_usd = tot_n = tot_w = 0
    for instr, ps in sorted(by.items()):
        Rs = [p / RISK_USD for p in ps]
        n = len(Rs); w = sum(1 for r in Rs if r > 0)
        exp = sum(Rs) / n; net_usd = sum(ps)
        print(f"{instr:10s} {n:>4d} {100*w/n:>5.0f} {exp:>7.3f} {sum(Rs):>7.2f} "
              f"{net_usd:>10.2f} {100*net_usd/ACCOUNT:>7.2f}")
        tot_R += sum(Rs); tot_usd += net_usd; tot_n += n; tot_w += w

    exp_all = tot_R / tot_n
    print(f"{'ALL':10s} {tot_n:>4d} {100*tot_w/tot_n:>5.0f} {exp_all:>7.3f} "
          f"{tot_R:>7.2f} {tot_usd:>10.2f} {100*tot_usd/ACCOUNT:>7.2f}")

    print(f"\nbacktest edge ~{BACKTEST_EXP:.2f}R · realised {exp_all:.3f}R "
          f"({100*exp_all/BACKTEST_EXP:.0f}% of backtest)")
    if tot_n < 10:
        verdict = f"TOO FEW TRADES ({tot_n}) — keep the demo running, re-run at 15-30+."
    elif exp_all >= GO_MIN_EXP and tot_usd > 0:
        verdict = (f"GO ✅ — real fills keep the edge (expectancy {exp_all:.3f}R ≥ "
                   f"{GO_MIN_EXP}). Confidence grows with more trades.")
    elif exp_all > 0:
        verdict = (f"MARGINAL — positive but thin ({exp_all:.3f}R < {GO_MIN_EXP}); real "
                   f"cost is eating most of the edge. Collect more before funded.")
    else:
        verdict = (f"NO-GO ✗ — real fills turn the edge negative ({exp_all:.3f}R). "
                   f"The live cost kills it; do not fund.")
    print(f"\n>>> KAPI 1: {verdict}")
    print("\n(Realised R = profit / risk-$, so it already includes spread + slippage + "
          "commission + swap. Sizing assumes every trade risked exactly "
          f"{RISK_PCT}%.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
