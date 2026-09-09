#!/usr/bin/env python3
"""De-risk parameter analysis. Optimising the drawdown de-risk against 'pass'
probability *looks* like it wants a more aggressive setting, but that is a model
artifact: the no-time-limit MC counts stuck-alive paths (survived to the step cap
without reaching +10%) as passes, and aggressive de-risk produces more of them.

Counting only paths that ACTUALLY reach +10%, the current 3/0.6/6/0.35 is better
(94.2% vs 91.8%) and faster (72 vs 79 median days) than the aggressive setting.
Conclusion: keep the current de-risk; it is already the right survival/progress
balance. Reproduce:
  PYTHONPATH=src:scripts python scripts/ftmo_derisk_opt.py
"""
import sys, random
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
from importlib import import_module
random.seed(41)

dp = import_module("ftmo_deep_portfolio")
legs, base_w, testD = dp.legs, dp.base_w, dp.testD


def series(weights, ds):
    out = []
    for d in ds:
        r = 0.0; t = False
        for s, w in weights.items():
            if d in legs[s]:
                r += w * legs[s][d]; t = True
        if t:
            out.append(r)
    return out


def mc(seq, dd1, m1, dd2, m2, target=10, dloss=5, oloss=10, N=20000, cap=400):
    """Honest accounting: report reached-target, stuck-alive and bust separately."""
    reached = stuck = bust = 0
    for _ in range(N):
        eq = 0.0; steps = 0; done = False
        while steps < cap:
            steps += 1; d = random.choice(seq); ddp = -eq
            if dd2 > 0 and ddp >= dd2: d *= m2
            elif dd1 > 0 and ddp >= dd1: d *= m1
            if d <= -dloss: bust += 1; done = True; break
            eq += d
            if eq <= -oloss: bust += 1; done = True; break
            if eq >= target: reached += 1; done = True; break
        if not done:
            stuck += 1
    return reached / N * 100, stuck / N * 100, bust / N * 100


if __name__ == "__main__":
    teS = series(base_w, testD)
    print("De-risk honest diagnosis (TEST days, count REACHED +10% only):")
    for name, pr in [("current 3/0.6/6/0.35", (3, 0.6, 6, 0.35)),
                     ("aggressive 2/0.5/4/0.25", (2, 0.5, 4, 0.25)),
                     ("no de-risk", (0, 1, 0, 1))]:
        rea, stk, bst = mc(teS, *pr)
        print(f"  {name:24s}: reached={rea:.1f}%  stuck-alive={stk:.1f}%  bust={bst:.1f}%")
