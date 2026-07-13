#!/usr/bin/env python3
"""Command-driven live ARMING for AurvexAI — owner-authorized, gate-preserving.

Turns the .env-side live gates ON without hand-editing .env, and captures the
live secrets securely (getpass — never touches shell history, never printed).

It DELIBERATELY does NOT cross every gate for you. Engine ``mode == live``
(gate 3) STILL requires the independent Telegram ``/livemode confirm <token>``
step + engine restart. That human-in-the-loop gate is the whole point of the
five-gate lock and this script never removes it — it never writes AX_MODE.

What it sets in .env (a timestamped, gitignored backup is made first):
  * LIVE_ENABLED=true            (gate 1 — config master switch)
  * LIVE_SEND_ORDERS=true        (gate 4 — the real-order arming switch)
  * LIVE_HUMAN_CONFIRM=<token>   (gate 2 — captured via getpass; gate 3 uses it)
  * BINANCE_API_KEY / _SECRET    (gate 5 — only prompted when currently blank)

What it NEVER does:
  * never writes AX_MODE=live  — mode=live belongs to Telegram /livemode confirm
  * never prints, logs or echoes any secret value
  * never runs the write without an explicit typed confirmation phrase
  * never a default — nothing happens unless invoked with --apply

After this script (still all command-driven):
  1. Telegram:  /livecheck                 (see the 4 gate checks)
  2. Telegram:  /livemode confirm <token>  (crosses gate 3 -> mode_request.json)
  3. Shell:     docker compose up -d --build engine
  4. Verify:    docker compose logs --tail=30 engine | grep -i "LIVE mode"
                -> must read "real sends ARMED"

Rollback (instant disarm):
  python3 scripts/arm_live.py --disarm --apply

Usage (Termius: one command per line, no && chaining):
  python3 scripts/arm_live.py             # dry-run: shows planned gate flips
  python3 scripts/arm_live.py --apply     # prompts (getpass) + writes .env
  python3 scripts/arm_live.py --disarm --apply   # instant rollback to disarmed
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import os
import shutil
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(__file__))
from update_env import _LINE_RE, _read_lines, _value_and_comment  # noqa: E402

# The exact phrase the operator must type on --apply (arming path only). This is
# defence against an accidental or automated run flipping real-order gates on.
CONFIRM_PHRASE = "ARM LIVE REAL MONEY"

# Non-secret gate flags this script is allowed to write, and ONLY these.
GATE_KEYS = ("LIVE_ENABLED", "LIVE_SEND_ORDERS")
# Secret keys it may set (values captured via getpass, never printed).
SECRET_KEYS_SETTABLE = ("LIVE_HUMAN_CONFIRM", "BINANCE_API_KEY",
                        "BINANCE_API_SECRET")
# Hard invariant: this script must NEVER write AX_MODE (that gate is Telegram's).
FORBIDDEN_KEYS = frozenset({"AX_MODE"})


def _current_values(lines: List[str], keys) -> Dict[str, str]:
    """Return {KEY: current_value} for keys present in .env (value may be '')."""
    out: Dict[str, str] = {}
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m = _LINE_RE.match(s)
        if m and m.group("key") in keys:
            val, _ = _value_and_comment(m.group("rest"))
            out[m.group("key")] = val
    return out


def _upsert(lines: List[str], gate_changes: Dict[str, str],
            secret_changes: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Idempotent in-place upsert. The returned log NEVER contains a secret
    value — secret keys log only as ``***updated***``/``***set***``."""
    seen = set()
    out: List[str] = []
    log: List[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        m = _LINE_RE.match(stripped) if stripped and not stripped.startswith("#") else None
        if not m:
            out.append(raw)
            continue
        key = m.group("key")
        ending = "\n" if raw.endswith("\n") else ""
        if key in gate_changes:
            old, comment = _value_and_comment(m.group("rest"))
            new = gate_changes[key]
            seen.add(key)
            if old == new:
                out.append(raw)
                log.append(f"  = {key} already {new} (no change)")
            else:
                out.append(f"{key}={new}{comment}{ending}")
                log.append(f"  ~ {key}: {old} -> {new}")
        elif key in secret_changes:
            _old, comment = _value_and_comment(m.group("rest"))  # never used/printed
            seen.add(key)
            out.append(f"{key}={secret_changes[key]}{comment}{ending}")
            log.append(f"  ~ {key}: ***updated*** (value hidden)")
        else:
            out.append(raw)
    appended = [k for k in (*GATE_KEYS, *SECRET_KEYS_SETTABLE)
                if (k in gate_changes or k in secret_changes) and k not in seen]
    if appended:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append("\n# -- live arming (scripts/arm_live.py) --\n")
        for k in appended:
            if k in gate_changes:
                out.append(f"{k}={gate_changes[k]}\n")
                log.append(f"  + {k}={gate_changes[k]} (appended)")
            else:
                out.append(f"{k}={secret_changes[k]}\n")
                log.append(f"  + {k}=***set*** (appended, value hidden)")
    return out, log


def _prompt_secrets(current: Dict[str, str]) -> Dict[str, str]:
    """Capture secrets via getpass. Returns only the ones the operator set.

    * LIVE_HUMAN_CONFIRM: prompted; empty input keeps any existing value.
    * BINANCE_API_KEY/_SECRET: prompted ONLY when currently blank/absent;
      an already-set key is left untouched (never re-read, never printed).
    """
    secret_changes: Dict[str, str] = {}

    existing_token = current.get("LIVE_HUMAN_CONFIRM", "")
    prompt = ("LIVE_HUMAN_CONFIRM token"
              + (" (Enter to keep existing): " if existing_token else ": "))
    token = getpass.getpass(prompt)
    if token:
        secret_changes["LIVE_HUMAN_CONFIRM"] = token

    for key, label in (("BINANCE_API_KEY", "Binance API key"),
                       ("BINANCE_API_SECRET", "Binance API secret")):
        if current.get(key, ""):
            print(f"  {key}: already set — leaving untouched.")
            continue
        val = getpass.getpass(f"{label} (blank = set later; live orders stay "
                              f"SIMULATED until keys present): ")
        if val:
            secret_changes[key] = val
    return secret_changes


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Command-driven live arming (dry-run by default). Flips the "
                    ".env live gates and captures secrets via getpass. NEVER "
                    "writes AX_MODE=live — mode=live stays a Telegram gate.")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    p.add_argument("--disarm", action="store_true",
                   help="set LIVE_ENABLED=false + LIVE_SEND_ORDERS=false "
                        "(instant rollback; no secrets touched, no prompt)")
    p.add_argument("--no-backup", action="store_true",
                   help="skip the .env.backup.<ts> copy on --apply")
    args = p.parse_args(argv)

    gate_val = "false" if args.disarm else "true"
    gate_changes = {k: gate_val for k in GATE_KEYS}

    # Hard invariant check (belt-and-braces; the script literally cannot name it).
    for k in (*gate_changes, *FORBIDDEN_KEYS):
        if k in FORBIDDEN_KEYS:
            assert k not in gate_changes, f"REFUSING: {k} is forbidden"

    env_path = args.env_file
    base_lines = _read_lines(env_path) if os.path.exists(env_path) else []
    current = _current_values(base_lines, SECRET_KEYS_SETTABLE)

    action = "DISARM" if args.disarm else "ARM"
    print(f"Target file : {env_path}")
    print(f"Action      : {action}")
    print(f"Mode        : {'APPLY (writing)' if args.apply else 'DRY-RUN (no write)'}")

    if not args.apply:
        # Dry-run: show gate flips only; never prompt for secrets.
        preview, log = _upsert(base_lines, gate_changes, {})
        print("Planned gate changes:")
        for c in log or ["  (none — already in that state)"]:
            print(c)
        if not args.disarm:
            missing = [k for k in SECRET_KEYS_SETTABLE
                       if not current.get(k, "")]
            print("\nOn --apply you will be prompted (getpass, hidden) for:")
            print("  LIVE_HUMAN_CONFIRM token (required to cross gate 2/3)")
            if missing:
                print("  " + ", ".join(k for k in missing
                                       if k != "LIVE_HUMAN_CONFIRM")
                      + "  (currently blank)")
        print("\nDry-run only. Re-run with --apply to write "
              "(a gitignored .env.backup.<ts> is made first).")
        return 0

    secret_changes: Dict[str, str] = {}
    if not args.disarm:
        print("\n⚠️  ARMING REAL-ORDER GATES. After this + Telegram "
              "/livemode confirm + restart, the engine sends REAL Binance "
              "orders with REAL money.")
        typed = input(f'Type EXACTLY  {CONFIRM_PHRASE}  to proceed: ')
        if typed.strip() != CONFIRM_PHRASE:
            print("Phrase mismatch — aborted. Nothing written.")
            return 1
        secret_changes = _prompt_secrets(current)
        token_ok = bool(secret_changes.get("LIVE_HUMAN_CONFIRM")
                        or current.get("LIVE_HUMAN_CONFIRM"))
        if not token_ok:
            print("REFUSING: no LIVE_HUMAN_CONFIRM token — gate 2 would fail. "
                  "Nothing written.")
            return 2

    new_lines, log = _upsert(base_lines, gate_changes, secret_changes)
    if os.path.exists(env_path) and not args.no_backup:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = f"{env_path}.backup.{ts}"
        shutil.copy2(env_path, backup)
        print(f"Backed up {env_path} -> {backup}  (gitignored)")
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    print(f"Wrote {env_path}. Changes:")
    for c in log or ["  (none)"]:
        print(c)

    if args.disarm:
        print("\nDisarmed. Also send  /papermode  on Telegram and restart:")
        print("  docker compose up -d --build engine")
        return 0

    keys_present = bool(current.get("BINANCE_API_KEY")
                        or secret_changes.get("BINANCE_API_KEY"))
    print("\nNext (all command-driven):")
    print("  1. Telegram:  /livecheck")
    print("  2. Telegram:  /livemode confirm <your_token>")
    print("  3. Shell:     docker compose up -d --build engine")
    print("  4. Verify:    docker compose logs --tail=30 engine | "
          "grep -i 'LIVE mode'   ->  'real sends ARMED'")
    if not keys_present:
        print("\n⚠️  Binance keys blank -> gate 5 open, adapter DISARMED, live "
              "orders stay SIMULATED. Re-run this script to add keys when ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
