#!/usr/bin/env python3
"""Live preflight from the shell — the same readiness audit as Telegram
/livecheck, printed as a GO/NO-GO table. Read-only: never sends an order,
never switches mode. Run before arming:

    python scripts/live_preflight.py

Exit code 0 = READY (no critical blocker), 1 = NOT READY.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import Engine


def main() -> int:
    eng = Engine(Config())
    rep = eng.live_preflight()
    mark = {True: "OK ", False: "NO ", None: "-- "}
    print("=" * 60)
    print("LIVE PREFLIGHT — pre-arm readiness audit")
    print("=" * 60)
    for r in rep["rows"]:
        crit = " !!" if (r["ok"] is False and r["critical"]) else "   "
        detail = f"   ({r['detail']})" if r["detail"] else ""
        print(f"  {mark[r['ok']]}{crit} {r['label']}{detail}")
    print("-" * 60)
    if rep["ready"]:
        print("READY — all critical gates + preconditions pass.")
        print("Arm via Telegram /live <token> (canary sizing applies).")
        return 0
    print("NOT READY — blocked by:")
    for b in rep["blockers"]:
        print(f"    - {b}")
    print("Real orders stay OFF until every blocker is cleared.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
