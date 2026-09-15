#!/usr/bin/env python3
"""Verify your broker's contract value (PPV) from a real closed trade.

Index PPV ("value per 1.0 price point per 1.0 lot") is broker-specific and the
one number that can silently mis-size your positions. After you close ONE trade
on the demo, plug in what happened and this backs out the true PPV so you can set
FTMO_GER40_PPV / FTMO_NAS100_PPV correctly.

    PPV = realised_pnl / (price_move × lots)

Usage (args or env):
    python scripts/ftmo_verify_ppv.py <entry> <exit> <lots> <realised_pnl>
  e.g. a GER40 long, 1 lot, 20000 -> 20100, +2500 pnl -> PPV = 2500/(100*1)=25.
"""
import os
import sys


def main(argv):
    try:
        if len(argv) >= 4:
            entry, exit_, lots, pnl = map(float, argv[:4])
        else:
            entry = float(os.environ["ENTRY"]); exit_ = float(os.environ["EXIT"])
            lots = float(os.environ["LOTS"]); pnl = float(os.environ["PNL"])
    except (ValueError, KeyError):
        print(__doc__); return 2
    move = abs(exit_ - entry)
    if move <= 0 or lots <= 0:
        print("price move and lots must be > 0"); return 2
    ppv = pnl / (move * lots) if pnl else 0.0
    print(f"price move {move:g} pts × {lots:g} lots")
    print(f"realised P&L {pnl:+g}")
    print(f"=> PPV ≈ {ppv:.4f}  (value per 1.0 point per 1.0 lot)")
    print(f"   set e.g.  export FTMO_GER40_PPV={round(abs(ppv), 2)}  (for that instrument)")
    print("   note: sign follows the trade; use the magnitude for PPV.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
