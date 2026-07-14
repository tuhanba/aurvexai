"""LIVE real-balance sync — sizing must run off the REAL Binance USDT-M wallet
balance, never the seeded paper ledger.

Pins the load-bearing safety behaviour:
  * paper mode is never touched (parity — no sync, no entry block);
  * live mode anchors the ledger to the real wallet balance from the account
    heartbeat, and audits it in the balance ledger;
  * live entries are BLOCKED until a real balance has been read at least once
    (fail-safe — never size a real order off an unsynced ledger);
  * a first-read failure keeps the block; a later good read lifts it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.storage import Storage


def _engine(tmp_path, mode="live"):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "eq.db")
    cfg.data_provider = "synthetic"
    cfg.mode = mode
    cfg.ltf = "1h"
    cfg.htf = "4h"
    cfg.initial_paper_balance = 200.0
    return Engine(cfg), cfg


# -- storage.set_balance -----------------------------------------------------

def test_set_balance_absolute_and_audited(tmp_path):
    db = Storage(str(tmp_path / "s.db"))
    db.ensure_balance(200.0)
    out = db.set_balance(512.5, mode="live", reason="live_balance_sync")
    assert out == 512.5
    assert db.get_balance() == 512.5
    synced = [r for r in db.get_ledger(limit=10)
              if r["reason"] == "live_balance_sync"]
    assert len(synced) == 1
    assert synced[0]["balance"] == 512.5
    assert abs(synced[0]["change"] - (512.5 - 200.0)) < 1e-9
    db.close()


# -- paper mode is untouched (parity) ----------------------------------------

def test_paper_mode_never_syncs_or_blocks(tmp_path):
    eng, cfg = _engine(tmp_path, mode="paper")
    eng.db.set_heartbeat("binance", {"futures_balance": {"total": 999.0}})
    assert eng._sync_live_equity() is False       # no-op in paper
    assert eng.db.get_balance() == 200.0          # seeded ledger untouched
    assert eng._live_entries_blocked() is False   # paper never blocked
    eng.db.close()


# -- live mode anchors to the real wallet balance ----------------------------

def test_live_sync_from_heartbeat_sets_real_balance(tmp_path):
    eng, cfg = _engine(tmp_path, mode="live")
    assert eng.db.get_balance() == 200.0          # seeded before sync
    assert eng._live_entries_blocked() is True    # blocked until first read
    eng.db.set_heartbeat("binance",
                         {"futures_balance": {"total": 512.5, "free": 500.0}})
    assert eng._sync_live_equity() is True
    assert eng.db.get_balance() == 512.5          # anchored to real wallet
    assert eng._live_equity_synced is True
    assert eng._live_entries_blocked() is False   # block lifted
    eng.db.close()


def test_live_sync_missing_balance_keeps_block(tmp_path):
    eng, cfg = _engine(tmp_path, mode="live")
    # no heartbeat at all
    assert eng._sync_live_equity() is False
    assert eng._live_entries_blocked() is True
    # heartbeat present but no usable total
    eng.db.set_heartbeat("binance", {"futures_balance": {"total": None}})
    assert eng._sync_live_equity() is False
    # zero / non-positive balance is not a valid anchor
    eng.db.set_heartbeat("binance", {"futures_balance": {"total": 0.0}})
    assert eng._sync_live_equity() is False
    assert eng.db.get_balance() == 200.0          # never overwritten with junk
    assert eng._live_entries_blocked() is True
    eng.db.close()


def test_live_block_lifts_after_recovery(tmp_path):
    eng, cfg = _engine(tmp_path, mode="live")
    assert eng._live_entries_blocked() is True
    eng.db.set_heartbeat("binance", {"futures_balance": {"total": 143.2}})
    assert eng._sync_live_equity() is True
    assert eng._live_entries_blocked() is False
    assert eng.db.get_balance() == 143.2
    eng.db.close()
