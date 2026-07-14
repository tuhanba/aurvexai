"""Safety tests for scripts/arm_live.py — the command-driven live armer.

The armer flips the .env-side live gates and captures secrets, but it must
NEVER (a) write AX_MODE=live, (b) write anything without the typed confirmation
phrase, (c) print a secret value, or (d) act in dry-run. These are load-bearing
safety invariants of the five-gate lock, so they are pinned here.
"""
import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.abspath(os.path.join(_HERE, "..", "scripts"))
sys.path.insert(0, _SCRIPTS)

spec = importlib.util.spec_from_file_location(
    "arm_live", os.path.join(_SCRIPTS, "arm_live.py"))
arm_live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm_live)


def _write_env(tmp_path, body):
    p = tmp_path / ".env"
    p.write_text(body)
    return str(p)


BASE_ENV = (
    "AX_MODE=paper\n"
    "LIVE_ENABLED=false\n"
    "LIVE_SEND_ORDERS=false\n"
    "LIVE_HUMAN_CONFIRM=\n"
    "BINANCE_API_KEY=\n"
    "BINANCE_API_SECRET=\n"
    "RISK_PCT=1.5\n"
)


def test_dry_run_writes_nothing(tmp_path, capsys):
    env = _write_env(tmp_path, BASE_ENV)
    rc = arm_live.main(["--env-file", env])
    assert rc == 0
    assert (tmp_path / ".env").read_text() == BASE_ENV  # untouched
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_apply_requires_confirm_phrase(tmp_path, monkeypatch, capsys):
    env = _write_env(tmp_path, BASE_ENV)
    monkeypatch.setattr("builtins.input", lambda *_: "nope")
    rc = arm_live.main(["--env-file", env, "--apply"])
    assert rc == 1
    assert (tmp_path / ".env").read_text() == BASE_ENV  # aborted, untouched


def test_apply_arms_gates_and_sets_token(tmp_path, monkeypatch):
    env = _write_env(tmp_path, BASE_ENV)
    monkeypatch.setattr("builtins.input", lambda *_: arm_live.CONFIRM_PHRASE)
    # token, then binance key, then binance secret
    answers = iter(["s3cr3t-token", "KEYVAL", "SECRETVAL"])
    monkeypatch.setattr(arm_live.getpass, "getpass", lambda *_: next(answers))
    rc = arm_live.main(["--env-file", env, "--apply", "--no-backup"])
    assert rc == 0
    text = (tmp_path / ".env").read_text()
    assert "LIVE_ENABLED=true" in text
    assert "LIVE_SEND_ORDERS=true" in text
    assert "LIVE_HUMAN_CONFIRM=s3cr3t-token" in text
    assert "BINANCE_API_KEY=KEYVAL" in text


def test_arm_sets_ax_mode_live(tmp_path, monkeypatch):
    # The live executor is built from AX_MODE at startup, so arming MUST set it.
    env = _write_env(tmp_path, BASE_ENV)
    monkeypatch.setattr("builtins.input", lambda *_: arm_live.CONFIRM_PHRASE)
    answers = iter(["tok", "K", "S"])
    monkeypatch.setattr(arm_live.getpass, "getpass", lambda *_: next(answers))
    arm_live.main(["--env-file", env, "--apply", "--no-backup"])
    text = (tmp_path / ".env").read_text()
    assert "AX_MODE=live" in text
    assert "AX_MODE=paper" not in text


def test_secret_values_never_printed(tmp_path, monkeypatch, capsys):
    env = _write_env(tmp_path, BASE_ENV)
    monkeypatch.setattr("builtins.input", lambda *_: arm_live.CONFIRM_PHRASE)
    answers = iter(["TOPSECRET_TOKEN_XYZ", "APIKEY_ZZZ", "APISECRET_QQQ"])
    monkeypatch.setattr(arm_live.getpass, "getpass", lambda *_: next(answers))
    arm_live.main(["--env-file", env, "--apply", "--no-backup"])
    out = capsys.readouterr().out
    assert "TOPSECRET_TOKEN_XYZ" not in out
    assert "APIKEY_ZZZ" not in out
    assert "APISECRET_QQQ" not in out
    assert "***" in out  # masked marker shown instead


def test_refuses_arm_without_token(tmp_path, monkeypatch, capsys):
    # No existing token and operator provides none -> gate 2 would fail.
    env = _write_env(tmp_path, BASE_ENV)
    monkeypatch.setattr("builtins.input", lambda *_: arm_live.CONFIRM_PHRASE)
    answers = iter(["", "", ""])  # blank token + blank keys
    monkeypatch.setattr(arm_live.getpass, "getpass", lambda *_: next(answers))
    rc = arm_live.main(["--env-file", env, "--apply", "--no-backup"])
    assert rc == 2
    assert (tmp_path / ".env").read_text() == BASE_ENV  # nothing written


def test_disarm_sets_gates_false_no_prompt(tmp_path, monkeypatch):
    armed = (BASE_ENV.replace("AX_MODE=paper", "AX_MODE=live")
             .replace("LIVE_ENABLED=false", "LIVE_ENABLED=true")
             .replace("LIVE_SEND_ORDERS=false", "LIVE_SEND_ORDERS=true"))
    env = _write_env(tmp_path, armed)

    def _boom(*_a, **_k):
        raise AssertionError("disarm must not prompt")

    monkeypatch.setattr("builtins.input", _boom)
    monkeypatch.setattr(arm_live.getpass, "getpass", _boom)
    rc = arm_live.main(["--env-file", env, "--disarm", "--apply", "--no-backup"])
    assert rc == 0
    text = (tmp_path / ".env").read_text()
    assert "AX_MODE=paper" in text          # mode rolled back
    assert "AX_MODE=live" not in text
    assert "LIVE_ENABLED=false" in text
    assert "LIVE_SEND_ORDERS=false" in text


def test_existing_keys_left_untouched(tmp_path, monkeypatch, capsys):
    body = BASE_ENV.replace("BINANCE_API_KEY=\n", "BINANCE_API_KEY=EXISTING_K\n").replace(
        "BINANCE_API_SECRET=\n", "BINANCE_API_SECRET=EXISTING_S\n")
    env = _write_env(tmp_path, body)
    monkeypatch.setattr("builtins.input", lambda *_: arm_live.CONFIRM_PHRASE)
    # only the token is prompted; keys already set must NOT be asked for
    monkeypatch.setattr(arm_live.getpass, "getpass", lambda *_: "newtok")
    rc = arm_live.main(["--env-file", env, "--apply", "--no-backup"])
    assert rc == 0
    text = (tmp_path / ".env").read_text()
    assert "BINANCE_API_KEY=EXISTING_K" in text  # preserved
    assert "BINANCE_API_SECRET=EXISTING_S" in text
