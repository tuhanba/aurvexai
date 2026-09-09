#!/usr/bin/env python3
"""Stress-test the pass-probability model: does it survive REALISTIC losing-streak
structure? The earlier Monte-Carlo resampled single days (iid), which breaks
autocorrelation. This resamples contiguous multi-day BLOCKS from the real
chronological account-return series, preserving streaks and runs.

Findings (2026-09-09):
  * Block bootstrap gives similar-to-higher pass prob than iid -> the iid estimate
    was NOT inflated by ignoring autocorrelation.
  * De-risk (v2.4) survives strongly: ~+8pt of pass rate even under streak-
    preserving resampling (its whole purpose is surviving clustered losses).
  * The allocation recommendation (cut NAS100, weight JP225 up) holds under both
    models (+1.5pt).
Caveat: blocks are resampled from a specific test period; a genuinely adverse
regime could be worse. The real safeguards remain low risk + de-risk + KAPI-1.

Run:  PYTHONPATH=src:scripts python scripts/ftmo_block_bootstrap.py
"""
import sys, random
sys.path.insert(0, "scripts"); sys.path.insert(0, "src")
from statistics import mean, pstdev
from importlib import import_module
random.seed(31)

dp = import_module("ftmo_deep_portfolio")
legs, base_w, testD = dp.legs, dp.base_w, dp.testD


def series(weights, day_subset):
    out = []
    for d in day_subset:            # already sorted
        r = 0.0; traded = False
        for s, w in weights.items():
            if d in legs[s]:
                r += w * legs[s][d]; traded = True
        if traded:
            out.append(r)
    return out


def mc_iid(day_ret, target=10, dloss=5, oloss=10, N=15000, derisk=True):
    if not day_ret:
        return 0
    npass = 0
    for _ in range(N):
        eq = 0.0; steps = 0
        while steps < 400:
            steps += 1; d = random.choice(day_ret)
            if derisk:
                dd = -eq
                if dd >= 6: d *= 0.35
                elif dd >= 3: d *= 0.60
            if d <= -dloss: break
            eq += d
            if eq <= -oloss: break
            if eq >= target: npass += 1; break
        else:
            npass += 1
    return npass / N * 100


def mc_block(seq, blk=5, target=10, dloss=5, oloss=10, N=15000, derisk=True):
    if len(seq) < blk + 1:
        return 0
    npass = 0; maxstart = len(seq) - blk
    for _ in range(N):
        eq = 0.0; steps = 0; busted = False
        while steps < 400 and not busted:
            st = random.randint(0, maxstart)
            for k in range(blk):
                steps += 1; d = seq[st + k]
                if derisk:
                    dd = -eq
                    if dd >= 6: d *= 0.35
                    elif dd >= 3: d *= 0.60
                if d <= -dloss: busted = True; break
                eq += d
                if eq <= -oloss: busted = True; break
                if eq >= target: npass += 1; busted = True; break
        if steps >= 400 and not busted:
            npass += 1
    return npass / N * 100


if __name__ == "__main__":
    teS = series(base_w, testD)
    print("Block-bootstrap stress-test (baseline weights, TEST days)")
    print(f"  iid bootstrap:          {mc_iid(teS):.1f}%")
    for blk in [3, 5, 10, 20]:
        print(f"  block bootstrap (b={blk:2d}):  {mc_block(teS, blk):.1f}%")
    print(f"  daily mean={mean(teS):+.3f}% std={pstdev(teS):.3f}% n={len(teS)}")
    print("\nDe-risk value under block bootstrap (b=10):")
    print(f"  with de-risk:    {mc_block(teS, 10, derisk=True):.1f}%")
    print(f"  without de-risk: {mc_block(teS, 10, derisk=False):.1f}%")
    rec = {"XAUUSD": 0.35, "XAGUSD": 0.35, "BTC": 0.30,
           "GER40": 0.25, "NAS100": 0.0, "JP225": 0.45}
    print("\nAllocation conclusion under block bootstrap (b=10, TEST):")
    print(f"  baseline:    {mc_block(series(base_w, testD), 10):.1f}%")
    print(f"  recommended: {mc_block(series(rec, testD), 10):.1f}%")
