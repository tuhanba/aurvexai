"""
Epoch reset rollback artifact (Phase 1).

The epoch reset must, BEFORE clearing anything, write a recoverable rollback
artifact: a redacted .env copy, a resolved-config snapshot (secrets excluded),
the git HEAD SHA + branch, and a DB backup. The existing reset behaviour is
preserved (shadow rows survive, new epoch label stamped).

Guardrail under test: NO .env secret value ever lands in the artifact.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import OPEN, new_id, now_ms
from aurvex.storage import Storage, write_rollback_artifact, _redact_env_text


SECRET_TOKEN = "123456789:AAsuperSECRETtokenValueShouldNeverLeak"
SECRET_KEY = "binanceApiKeySECRET_DO_NOT_LEAK_abcdef"


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "data" / "roll.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.epoch_label = "wave3"
    cfg.initial_paper_balance = 200.0
    # A secret living in config must not appear in the snapshot.
    cfg.telegram_bot_token = SECRET_TOKEN
    cfg.telegram_chat_id = "987654321"
    return cfg


def _write_env(tmp_path) -> str:
    env = tmp_path / ".env"
    env.write_text(
        "AX_MODE=paper\n"
        f"TELEGRAM_BOT_TOKEN={SECRET_TOKEN}\n"
        f"BINANCE_API_SECRET={SECRET_KEY}\n"
        "BINANCE_API_KEY=plainkey_should_be_redacted_too\n"
        "RISK_PCT=2.0\n"
        "# a comment line\n"
    )
    return str(env)


def _seed_shadow(db: Storage, bar_ts: int) -> None:
    db.insert_shadow({
        "id": new_id(), "ts": now_ms(), "source": "rejected", "symbol": "BTCUSDT",
        "side": "LONG", "setup_type": "momentum_breakout", "score": 70.0,
        "entry": 100.0, "stop_loss": 98.0, "tp1": 103.0,
        "outcome": "TP", "outcome_time": now_ms(), "r_multiple": 1.4,
        "bars": 5, "signal_bar_ts": bar_ts, "last_bar_ts": bar_ts + 60_000,
        "epoch": "legacy",
    })


def test_redact_env_text_redacts_only_secret_values():
    raw = (
        "AX_MODE=paper\n"
        f"TELEGRAM_BOT_TOKEN={SECRET_TOKEN}\n"
        f"BINANCE_API_SECRET={SECRET_KEY}\n"
        "RISK_PCT=2.0\n"
        "# comment\n"
    )
    out = _redact_env_text(raw)
    assert SECRET_TOKEN not in out
    assert SECRET_KEY not in out
    assert "TELEGRAM_BOT_TOKEN=<redacted>" in out
    assert "BINANCE_API_SECRET=<redacted>" in out
    # Non-secret keys and comments survive untouched.
    assert "RISK_PCT=2.0" in out
    assert "# comment" in out
    assert "AX_MODE=paper" in out


def test_artifact_created_with_all_parts(tmp_path):
    cfg = _cfg(tmp_path)
    env_path = _write_env(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    _seed_shadow(db, bar_ts=1_000)
    db.close()

    backups_root = str(tmp_path / "backups")
    art_dir = write_rollback_artifact(
        cfg, cfg.db_path, epoch_label=cfg.epoch_label,
        backups_root=backups_root, env_path=env_path)

    assert os.path.isdir(art_dir)
    # config snapshot parses
    with open(os.path.join(art_dir, "config_snapshot.json")) as fh:
        snap = json.load(fh)
    assert snap["initial_paper_balance"] == 200.0
    assert snap["risk_pct"] == cfg.risk_pct
    # git head present
    with open(os.path.join(art_dir, "git_head.json")) as fh:
        git = json.load(fh)
    assert git["sha"] and git["sha"] != ""
    assert "branch" in git
    # db backup present
    assert os.path.exists(os.path.join(art_dir, "db_backup", "roll.db"))
    # redacted env present
    assert os.path.exists(os.path.join(art_dir, "env_redacted.txt"))


def test_no_secret_leaks_into_any_artifact_file(tmp_path):
    cfg = _cfg(tmp_path)
    env_path = _write_env(tmp_path)
    Storage(cfg.db_path).close()

    backups_root = str(tmp_path / "backups")
    art_dir = write_rollback_artifact(
        cfg, cfg.db_path, epoch_label=cfg.epoch_label,
        backups_root=backups_root, env_path=env_path)

    # Scan every text artifact: no secret string may appear anywhere.
    for fname in ("env_redacted.txt", "config_snapshot.json", "git_head.json"):
        path = os.path.join(art_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            blob = fh.read()
        assert SECRET_TOKEN not in blob, f"token leaked into {fname}"
        assert SECRET_KEY not in blob, f"api secret leaked into {fname}"


def test_reset_preserves_shadows_and_stamps_epoch(tmp_path):
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("oldepoch")
    _seed_shadow(db, bar_ts=1_000)
    _seed_shadow(db, bar_ts=2_000)
    result = db.reset_for_new_epoch(cfg.initial_paper_balance, label="wave3")
    db.close()

    assert result["shadows_kept"] == 2
    assert result["new_epoch"]["label"] == "wave3"

    db2 = Storage(cfg.db_path)
    # Shadow rows survived the reset.
    n = db2.conn.execute("SELECT COUNT(*) AS n FROM shadows").fetchone()["n"]
    assert n == 2
    # New epoch label written to meta.
    epoch = db2.get_meta("epoch")
    assert epoch["label"] == "wave3"
    db2.close()


def test_never_overwrites_existing_backup(tmp_path):
    cfg = _cfg(tmp_path)
    env_path = _write_env(tmp_path)
    Storage(cfg.db_path).close()
    backups_root = str(tmp_path / "backups")

    a = write_rollback_artifact(cfg, cfg.db_path, epoch_label="wave3",
                                backups_root=backups_root, env_path=env_path)
    # A tiny sleep-free guarantee: ts is ms; force a distinct dir by calling again
    # after a millisecond boundary is not guaranteed, so just assert the first
    # artifact still exists after a second write (no deletion of prior backups).
    b = write_rollback_artifact(cfg, cfg.db_path, epoch_label="wave3",
                                backups_root=backups_root, env_path=env_path)
    assert os.path.isdir(a)
    assert os.path.isdir(b)
