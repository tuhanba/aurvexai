#!/usr/bin/env python3
"""
AurvexAI entrypoint.

Usage:
    python main.py engine      # run the live paper engine loop (uses DATA_PROVIDER)
    python main.py dashboard   # run the Flask dashboard on DASHBOARD_PORT
    python main.py demo        # fast synthetic end-to-end run (offline, ~40 cycles)
    python main.py backtest    # offline seeded backtest, prints metrics JSON
    python main.py walkforward # Block 6: real-data (or synthetic) OOS walk-forward
                               # decision table per profile, net-of-cost (+funding)
    python main.py reset       # clear trades/funnel/signals, keep shadow data, new epoch
    python main.py report      # read-only Governor system report (add --telegram to send)
    python main.py telegram-test   # in-container Telegram diagnostic (getMe + send)

All configuration comes from the environment / .env (see .env.example).
No secrets are read from anywhere but the environment. Live trading is OFF.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from aurvex.config import load_config  # noqa: E402


def _print_help() -> None:
    print(__doc__)


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    cmd = argv[0]
    cfg = load_config()
    cfg.validate()

    if cmd == "engine":
        from aurvex.engine import run_engine
        run_engine(cfg)
        return 0

    if cmd == "dashboard":
        from aurvex.dashboard.app import run_dashboard
        run_dashboard(cfg)
        return 0

    if cmd == "demo":
        # Force the synthetic provider so it runs with no network/keys.
        cfg.data_provider = "synthetic"
        from aurvex.engine import run_engine
        cycles = int(os.environ.get("DEMO_CYCLES", "40"))
        run_engine(cfg, max_cycles=cycles, sleep_override=0.0)
        return 0

    if cmd == "backtest":
        from aurvex.backtest import run_backtest_offline
        bars = int(os.environ.get("BACKTEST_BARS", "1500"))
        metrics = run_backtest_offline(cfg, bars=bars)
        print(json.dumps(metrics, indent=2, default=str))
        return 0

    if cmd == "walkforward":
        return _run_walkforward(cfg)

    if cmd == "reset":
        return _run_reset(cfg)

    if cmd == "report":
        from aurvex.governor import run_report
        want_tg = "--telegram" in argv[1:]
        return run_report(cfg, telegram=want_tg)

    if cmd == "balance-reset":
        return _run_balance_reset(cfg)

    if cmd in ("telegram-test", "telegram_selftest"):
        return _telegram_selftest(cfg)

    print(f"unknown command: {cmd}\n")
    _print_help()
    return 2


def _run_walkforward(cfg) -> int:
    """Block 6: real-data (or synthetic-fallback) out-of-sample walk-forward.

    All knobs are env-driven (no hard-coding). On a host without Binance access
    it falls back to synthetic data and loudly marks the output as NOT live
    evidence. Live remains OFF regardless of the result.
    """
    from aurvex.walkforward import (WalkForwardConfig, print_report,
                                    run_walkforward_analysis)

    wf = WalkForwardConfig(
        oos_bars=int(os.environ.get("WF_OOS_BARS", "1000")),
        step_bars=int(os.environ.get("WF_STEP_BARS", "1000")),
        warmup_bars=int(os.environ.get("WF_WARMUP_BARS", "400")),
        funding_rate_8h=float(os.environ.get("WF_FUNDING_8H",
                                             str(cfg.funding_rate_8h or 0.0001))),
        mc_sims=int(os.environ.get("WF_MC_SIMS", "500")),
    )
    syms = os.environ.get("WF_SYMBOLS")
    symbols = [s.strip() for s in syms.split(",") if s.strip()] if syms else None
    limit = int(os.environ.get("WF_LIMIT", "3000"))
    timeframe = os.environ.get("WF_TIMEFRAME", cfg.ltf)
    htf = os.environ.get("WF_HTF", cfg.htf)

    print("=== AurvexAI Block 6 — walk-forward analysis ===")
    print(f"timeframe={timeframe}  htf={htf}  limit={limit}  "
          f"oos={wf.oos_bars} step={wf.step_bars} warmup={wf.warmup_bars}")
    results, source, data = run_walkforward_analysis(
        cfg, symbols=symbols, timeframe=timeframe, limit=limit, wf_cfg=wf, htf=htf)
    print(f"data source: {source}  symbols: {list(data.keys())}")
    if source == "synthetic":
        bar = "!" * 72
        print(f"\n{bar}\nSYNTHETIC DATA — NOT LIVE EVIDENCE (Binance unreachable / "
              f"no cache).\nRun on a Binance-reachable host for the real decision "
              f"table.\n{bar}")
    print()
    print(print_report(results))
    return 0


def _run_reset(cfg) -> int:
    """Clear trading data, preserve shadow learner rows, seed a new epoch.

    Writes a redacted rollback artifact (env_redacted, config snapshot, git HEAD,
    DB backup) BEFORE clearing anything, so the prior epoch is always recoverable.
    """
    from aurvex.storage import Storage, write_rollback_artifact

    print("=== AurvexAI Epoch Reset ===")
    print(f"DB             : {cfg.db_path}")
    print(f"Shadows        : KEPT (learning history preserved)")
    print(f"Trades / funnel / signals / ledger : CLEARED")
    print(f"New balance    : {cfg.initial_paper_balance} USDT")
    print()

    # Rollback artifact first — never delete an existing backup; failure here must
    # not block the reset, but we surface the path so it can be used to roll back.
    # Root the artifact NEXT TO the DB (e.g. data/backups) so it lands on the same
    # persisted volume in Docker rather than an ephemeral container working dir.
    backups_root = os.path.join(os.path.dirname(cfg.db_path) or ".", "backups")
    try:
        art_dir = write_rollback_artifact(cfg, cfg.db_path, epoch_label=cfg.epoch_label,
                                          backups_root=backups_root)
        print(f"✓ Rollback artifact : {art_dir}")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"! Rollback artifact FAILED (continuing reset): {exc}")
    print()

    db = Storage(cfg.db_path)
    result = db.reset_for_new_epoch(cfg.initial_paper_balance, label=cfg.epoch_label)
    db.close()

    print(f"✓ Shadows preserved : {result['shadows_kept']} rows")
    print(f"✓ Tables cleared    : {', '.join(result['tables_cleared'])}")
    print(f"✓ New balance       : {result['new_balance']} USDT")
    print(f"✓ New epoch         : {result['new_epoch']['label']} "
          f"({result['new_epoch']['id']})")
    print()
    print("Done. Restart the engine:")
    print("  docker compose restart engine")

    # Optional: Telegram reset notification (best-effort, never fatal).
    try:
        from aurvex.telegram import build_notifier
        notifier = build_notifier(cfg)
        notifier.reset_completed(cfg.epoch_label, result["new_balance"],
                                 result["shadows_kept"])
    except Exception:
        pass

    return 0


def _run_balance_reset(cfg) -> int:
    """Reset only the paper balance, keep all trades and shadow data."""
    from aurvex.storage import Storage

    print("=== AurvexAI Balance Reset ===")
    print(f"DB             : {cfg.db_path}")
    print(f"Trades / shadows / funnel : KEPT")
    print(f"Balance only   : reset to {cfg.initial_paper_balance} USDT")
    print()

    db = Storage(cfg.db_path)
    result = db.reset_balance_only(cfg.initial_paper_balance)
    db.close()

    print(f"✓ Old balance   : {result['old_balance']:.4f} USDT")
    print(f"✓ New balance   : {result['new_balance']} USDT")
    print(f"✓ Trades kept   : {result['trades_kept']} rows")
    print(f"✓ Shadows kept  : {result['shadows_kept']} rows")
    print()
    print("Done. Restart the engine:")
    print("  docker compose restart engine")
    return 0


def _telegram_selftest(cfg) -> int:
    """In-container Telegram diagnostic. Prints status, runs getMe, sends one
    test message. NEVER prints the token or chat id - only booleans + health.
    """
    from aurvex.telegram import build_notifier, TelegramNotifier

    print("=== AurvexAI Telegram self-test ===")
    print(f"TELEGRAM_ENABLED   : {cfg.telegram_enabled}")
    print(f"bot token set      : {bool(cfg.telegram_bot_token)}")
    print(f"chat id set        : {bool(cfg.telegram_chat_id)}")

    notifier = build_notifier(cfg)
    print(f"notifier selected  : {type(notifier).__name__}")
    if not isinstance(notifier, TelegramNotifier):
        print("RESULT             : Telegram NOT active.")
        print(f"reason             : {notifier.health().get('note')}")
        print("Fix: set TELEGRAM_ENABLED=true and provide TELEGRAM_BOT_TOKEN + "
              "TELEGRAM_CHAT_ID in the container environment (.env / compose).")
        return 1

    print("\n-- getMe (token + DNS/HTTPS reachability) --")
    ok = notifier.verify()
    h = notifier.health()
    print(f"getMe ok           : {ok}")
    if h.get("bot_username"):
        print(f"bot username       : @{h['bot_username']}")
    if not ok:
        print(f"last_error         : {h.get('last_error')}")
        print("RESULT             : getMe FAILED (bad token or network). No message sent.")
        return 2

    print("\n-- sendMessage (test) --")
    sent = notifier.send("✅ AurvexAI Telegram self-test OK")
    h = notifier.health()
    print(f"send ok            : {sent}")
    print(f"sends_ok/failed    : {h.get('sends_ok')}/{h.get('sends_failed')}")
    if not sent:
        print(f"last_error         : {h.get('last_error')}")
        print("RESULT             : getMe ok but sendMessage FAILED. Most likely the "
              "chat id is wrong, or the bot was never /start-ed in that chat.")
        return 3
    print("RESULT             : Telegram fully healthy (getMe + sendMessage).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
