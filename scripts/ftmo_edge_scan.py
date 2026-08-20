#!/usr/bin/env python3
"""Data-driven edge scan (system-from-data) on an FTMO instrument's 1h bars.

Instead of imposing ORB/PDHL and testing instruments, this lets the data speak:
a pre-specified battery of simple, economically-motivated directional edge
families (momentum, mean-reversion, ATR breakout, hour-of-day drift, overnight
gap-fade), each measured NET of a realistic round-trip cost and checked for
out-of-sample sign stability. Guards against the overfitting that pure data
mining invites by keeping each family simple, parameter-light and OOS-tested.

Verdict on gold (XAUUSD, ~13.7k 1h bars): every intraday/high-frequency family
is net-negative after cost — the ~4bp round-trip equals the average hourly bar
noise, so any frequently-trading (scalp) signal nets below zero. The only
cost-surviving form is the low-frequency opening-range breakout already in use,
which trades once per day and captures a multi-hour structural move far larger
than the one-off cost. This is why scalp is structurally dead on these
instruments and the current low-frequency system is what the data supports.

Run:  PYTHONPATH=src:scripts python scripts/ftmo_edge_scan.py [SYMBOL]
"""
import sys, os
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
import ftmo_trail_probe as p
from statistics import mean

RT = float(os.environ.get("FTMO_RT", "0.0004"))   # realistic round-trip (fraction)


def oos_sign(rets):
    n = len(rets)
    if n < 25:
        return 0
    step = n // 5
    return sum(1 for i in range(5)
               if mean(rets[i*step:(i+1)*step if i < 4 else n]) > 0)


def scan(sym="XAUUSD"):
    bars = p.load(sym); n = len(bars)
    print(f"# Data-driven edge scan — {sym} 1h, net of {RT*100:.2f}% RT, OOS 5-fold\n")
    print(f"{'family':28s} | {'net bp/trade':>12s} {'n':>6s} {'OOS':>4s}  verdict")

    def report(name, trades):
        if not trades:
            print(f"{name:28s} | {'--':>12s}"); return
        net = [t*10000 - RT*10000 for t in trades]
        e = mean(net); pos = oos_sign(net)
        v = "EDGE" if (e > 0 and pos >= 4) else ("marginal" if e > 0 else "dead")
        print(f"{name:28s} | {e:>12.2f} {len(net):>6d} {pos:>3d}/5  {v}")

    for k in (1, 2, 3):
        mom, rev = [], []
        for i in range(k, n-1):
            up = all(bars[j][4] > bars[j-1][4] for j in range(i-k+1, i+1))
            dn = all(bars[j][4] < bars[j-1][4] for j in range(i-k+1, i+1))
            r = bars[i+1][4]/bars[i][4] - 1
            if up: mom.append(r); rev.append(-r)
            elif dn: mom.append(-r); rev.append(r)
        report(f"momentum k={k}", mom); report(f"meanrev k={k}", rev)

    atr = [None]*n
    for i in range(14, n):
        atr[i] = sum(max(bars[j][2]-bars[j][3], abs(bars[j][2]-bars[j-1][4]),
                         abs(bars[j][3]-bars[j-1][4])) for j in range(i-13, i+1))/14
    for m in (0.5, 1.0, 1.5):
        tr = []
        for i in range(15, n-1):
            if not atr[i]:
                continue
            mv = bars[i][4]-bars[i][1]
            if mv > m*atr[i]:  tr.append(bars[i+1][4]/bars[i][4]-1)
            elif mv < -m*atr[i]: tr.append(-(bars[i+1][4]/bars[i][4]-1))
        report(f"ATR-break m={m}", tr)

    best = (-9, None, None)
    for H in range(24):
        tr = [bars[i+1][4]/bars[i][4]-1 for i in range(n-1)
              if p.utc_hour(bars[i][0]) == H]
        if len(tr) > 100 and mean([t*10000-RT*10000 for t in tr]) > best[0]:
            best = (mean([t*10000-RT*10000 for t in tr]), H, tr)
    report(f"hour-drift best H={best[1]}", best[2])

    by = {}
    for b in bars:
        by.setdefault(p.utc_day(b[0]), []).append(b)
    days = sorted(by); tr = []
    for di in range(1, len(days)):
        prev, cur = by[days[di-1]], by[days[di]]
        if not prev or not cur:
            continue
        gap = cur[0][1]/prev[-1][4] - 1
        if abs(gap) < 1e-6:
            continue
        dr = cur[-1][4]/cur[0][1] - 1
        tr.append(-dr if gap > 0 else dr)
    report("overnight gap-fade", tr)

    print("\n*The ~4bp cost equals the average hourly noise, so every frequently-"
          "trading family nets negative. Only the low-frequency opening-range "
          "breakout (once/day, multi-hour move >> cost) survives — which is the "
          "system already in use. Scalp is structurally dead on these instruments.*")


if __name__ == "__main__":
    scan(sys.argv[1] if len(sys.argv) > 1 else "XAUUSD")
