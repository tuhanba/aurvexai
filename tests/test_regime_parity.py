"""Phase 1 PARITY guarantee.

The observational regime layer must not change any decision or sizing. These
tests prove:
  1. DecisionEngine.decide() never reads the ensemble flag (it can't — the flag
     lives on the engine, not the brain).
  2. The engine's _decide() produces byte-identical SIZING with the ensemble
     flag OFF vs ON — the flag only ADDS observational metadata keys.
  3. A synthetic cycle runs clean with the ensemble ON and writes regime history;
     with it OFF, no regime history is written and behaviour is the baseline.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.filters import PortfolioView
from aurvex.models import now_ms

SIZING_FIELDS = ("decision", "entry", "stop_loss", "tp1", "tp2", "tp3",
                 "position_size", "leverage", "risk_pct", "max_loss", "score")


def _engine(tmp_path, name, ensemble):
    c = Config()
    c.data_provider = "synthetic"
    c.mode = "paper"
    c.db_path = str(tmp_path / name)
    c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    c.ltf_limit = 300
    c.global_ranking = True
    c.regime_ensemble_enabled = ensemble
    return Engine(c)


def _first_allow_pair(e_off, e_on):
    """Detect the same candidates on both engines and return the first
    (decision_off, decision_on) for a matching setup on a shared snapshot."""
    # Use a single shared snapshot so both engines decide on identical inputs.
    sym = "BTC/USDT:USDT"
    snap = e_off.provider.get_snapshot(sym, list(e_off._snapshot_tfs))
    assert snap is not None
    pf = PortfolioView(balance=200.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    sigs = e_off._detect_candidates(snap)
    assert sigs, "synthetic data should produce at least one signal"
    pairs = []
    for s in sigs:
        d_off = e_off._decide(s, snap, pf)
        d_on = e_on._decide(s, snap, pf)
        pairs.append((s.setup_type, d_off, d_on))
    return pairs


def test_decide_sizing_identical_off_vs_on(tmp_path):
    e_off = _engine(tmp_path, "off.db", ensemble=False)
    e_on = _engine(tmp_path, "on.db", ensemble=True)
    pairs = _first_allow_pair(e_off, e_on)
    for setup, d_off, d_on in pairs:
        for f in SIZING_FIELDS:
            assert getattr(d_off, f) == getattr(d_on, f), (
                f"{setup}: field {f} diverged with the ensemble ON "
                f"({getattr(d_off, f)!r} != {getattr(d_on, f)!r})")


def test_ensemble_off_adds_no_regime_metadata(tmp_path):
    e_off = _engine(tmp_path, "off2.db", ensemble=False)
    e_on = _engine(tmp_path, "on2.db", ensemble=True)
    pairs = _first_allow_pair(e_off, e_on)
    for setup, d_off, d_on in pairs:
        # OFF: no regime/policy keys leak into decision metadata.
        assert "policy_version" not in d_off.metadata
        assert "regime_label" not in d_off.metadata
        # ON: the observational stamp is present (policy_version always; regime
        # label only once a state has been computed — None before the first cycle).
        assert d_on.metadata.get("policy_version") == e_on.cfg.policy_version


def test_cycle_writes_regime_history_when_on(tmp_path):
    e = _engine(tmp_path, "cyc_on.db", ensemble=True)
    e._regime_next_ms = 0  # force a compute this cycle
    asyncio.run(e._cycle())
    latest = e.db.latest_regime()
    assert latest is not None, "regime history row should be written when ON"
    assert "label" in latest and "confidence" in latest
    # The engine holds the state for the dashboard.
    assert e._regime_state is not None


def test_cycle_writes_no_regime_history_when_off(tmp_path):
    e = _engine(tmp_path, "cyc_off.db", ensemble=False)
    asyncio.run(e._cycle())
    assert e.db.latest_regime() is None
    assert e._regime_state is None


def test_market_regime_legacy_path_untouched(tmp_path):
    """The legacy sizing-facing regime read must be identical whether or not the
    observational ensemble is enabled (it is a separate code path)."""
    e_off = _engine(tmp_path, "leg_off.db", ensemble=False)
    e_on = _engine(tmp_path, "leg_on.db", ensemble=True)
    r_off = e_off._market_regime()
    r_on = e_on._market_regime()
    # Same provider + symbol + TF → same score/adx keys and values.
    assert r_off.get("score") == r_on.get("score")
    assert r_off.get("adx") == r_on.get("adx")
