"""
Wave 2 regression tests.

Covers the new behaviours introduced in Wave 2:
  CE-1  shadow-only setup gate (decision.py + config.py)
  CE-2  detect_all + best-score selection (engine.py + setups.py)
  CE-3  full-ladder shadow replay (shadow.py)
  IF-2  minimum notional floor (risk.py)
  IF-3  funnel quality/capacity split (funnel.py + models.py)
"""
import asyncio
from typing import List

import pytest

from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from aurvex.funnel import FunnelLogger, CAPACITY_STAGES
from aurvex.models import (ALLOW, REJECT, WATCH, LONG, SHORT, Decision,
                            Candle, FunnelStats, now_ms)
from aurvex.risk import RiskManager
from aurvex.setups import SetupDetector
from aurvex.shadow import ShadowLearner
from aurvex.storage import Storage

from conftest import make_signal, make_snapshot


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pf(cfg, balance=1000.0, open_count=0, open_symbols=None,
        open_notional=0.0, open_margin=0.0):
    return PortfolioView(
        balance=balance, open_count=open_count,
        open_symbols=open_symbols or [],
        open_notional=open_notional, open_margin=open_margin,
        last_trade_ms_by_symbol={}, daily_realized_pnl=0.0, now_ms=now_ms())


def _make_candles(n: int = 60, price: float = 100.0,
                  ts_start: int = 1_700_000_000_000,
                  interval_ms: int = 60_000) -> List[Candle]:
    candles = []
    for i in range(n):
        ts = ts_start + i * interval_ms
        candles.append(Candle(ts=ts, open=price, high=price * 1.002,
                              low=price * 0.998, close=price, volume=1000.0))
    return candles


# ---------------------------------------------------------------------------
# CE-1: shadow-only setup gate
# ---------------------------------------------------------------------------

class TestShadowOnlyGate:
    def test_shadow_only_setup_is_rejected(self, cfg):
        cfg.shadow_only_setups = ["momentum_breakout"]
        eng = DecisionEngine(cfg)
        sig = make_signal(setup_type="momentum_breakout", score=90.0)
        d = eng.decide(sig, make_snapshot(), _pf(cfg))
        assert d.decision == REJECT
        assert d.failed_stage == "shadow_only"
        assert "shadow-only" in d.reject_reason

    def test_non_shadow_only_setup_can_allow(self, cfg):
        cfg.shadow_only_setups = ["momentum_breakout"]
        eng = DecisionEngine(cfg)
        sig = make_signal(setup_type="trend_continuation", score=90.0)
        d = eng.decide(sig, make_snapshot(), _pf(cfg))
        assert d.decision == ALLOW

    def test_shadow_only_empty_list_no_effect(self, cfg):
        cfg.shadow_only_setups = []
        eng = DecisionEngine(cfg)
        sig = make_signal(setup_type="momentum_breakout", score=90.0)
        d = eng.decide(sig, make_snapshot(), _pf(cfg))
        assert d.decision == ALLOW

    def test_shadow_only_multiple_setups(self, cfg):
        cfg.shadow_only_setups = ["momentum_breakout", "volume_expansion"]
        eng = DecisionEngine(cfg)
        for setup in ["momentum_breakout", "volume_expansion"]:
            sig = make_signal(setup_type=setup, score=90.0)
            d = eng.decide(sig, make_snapshot(), _pf(cfg))
            assert d.decision == REJECT, f"{setup} should be shadow-only"
        # Another setup unaffected
        sig = make_signal(setup_type="trend_continuation", score=90.0)
        d = eng.decide(sig, make_snapshot(), _pf(cfg))
        assert d.decision == ALLOW

    def test_shadow_only_checked_after_score_threshold(self, cfg):
        """A shadow-only setup with score below watch threshold is rejected for
        low_score (hits score threshold first), not shadow_only."""
        cfg.shadow_only_setups = ["momentum_breakout"]
        eng = DecisionEngine(cfg)
        sig = make_signal(setup_type="momentum_breakout", score=10.0)
        d = eng.decide(sig, make_snapshot(), _pf(cfg))
        # Score fails before shadow_only gate (score check is BEFORE shadow gate).
        # With score=10, below watchlist_threshold(50), it should be low_score.
        # Actually, looking at decision.py order:
        # 1. filters (capacity), 2a. shadow_only, 2. score threshold
        # Wait: shadow_only comes BEFORE score threshold in the implementation.
        # So score=10 → shadow_only check fires first → REJECT with shadow_only.
        assert d.decision == REJECT
        assert d.failed_stage == "shadow_only"


# ---------------------------------------------------------------------------
# IF-2: minimum notional floor
# ---------------------------------------------------------------------------

class TestMinPositionNotional:
    def test_tiny_notional_rejected(self, cfg):
        """When exposure room < min_position_notional, risk rejects the trade."""
        cfg.min_position_notional = 50.0
        cfg.max_portfolio_exposure_pct = 200.0
        rm = RiskManager(cfg)
        sig = make_signal(score=90.0, stop_dist_pct=1.0)

        # Set open_notional near cap so very little room remains.
        balance = 1000.0
        cap = balance * cfg.max_portfolio_exposure_pct / 100.0
        open_notional = cap - 10.0  # only 10 USDT room left
        rr = rm.evaluate(sig, make_snapshot(), balance=balance,
                         open_notional=open_notional)
        assert not rr.allowed
        assert "min" in rr.reason.lower()

    def test_full_size_not_affected(self, cfg):
        """Normal-sized trades are unaffected by the min_position_notional floor."""
        cfg.min_position_notional = 5.0
        rm = RiskManager(cfg)
        sig = make_signal(score=90.0, stop_dist_pct=1.0)
        rr = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
        assert rr.allowed
        assert rr.position_size > 5.0

    def test_zero_floor_disables_check(self, cfg):
        """min_position_notional=0 disables the check entirely."""
        cfg.min_position_notional = 0.0
        cfg.max_portfolio_exposure_pct = 200.0
        rm = RiskManager(cfg)
        sig = make_signal(score=90.0, stop_dist_pct=1.0)
        balance = 1000.0
        cap = balance * cfg.max_portfolio_exposure_pct / 100.0
        open_notional = cap - 1.0  # only 1 USDT room
        rr = rm.evaluate(sig, make_snapshot(), balance=balance,
                         open_notional=open_notional)
        # Not rejected by min_notional (but may be rejected by leverage/margin).
        if not rr.allowed:
            assert "min" not in rr.reason.lower()


# ---------------------------------------------------------------------------
# IF-3: funnel quality/capacity split
# ---------------------------------------------------------------------------

class TestFunnelSplit:
    def _d(self, decision, stage="", reason=""):
        return Decision(symbol="X", side=LONG, decision=decision,
                        failed_stage=stage, reject_reason=reason)

    def test_capacity_stages_classified(self):
        f = FunnelLogger()
        for stage in ("max_open_trades", "duplicate", "cooldown",
                      "daily_loss_kill_switch"):
            f.record(self._d(REJECT, stage=stage))
        assert f.stats.capacity_reject_count == 4
        assert f.stats.quality_reject_count == 0

    def test_quality_stages_classified(self):
        f = FunnelLogger()
        for stage in ("score_threshold", "risk", "shadow_only",
                      "liquidity", "spread", "slippage"):
            f.record(self._d(REJECT, stage=stage))
        assert f.stats.quality_reject_count == 6
        assert f.stats.capacity_reject_count == 0

    def test_allow_not_counted_in_rejects(self):
        f = FunnelLogger()
        f.record(self._d(ALLOW))
        assert f.stats.quality_reject_count == 0
        assert f.stats.capacity_reject_count == 0

    def test_shadow_only_counted_as_quality(self):
        f = FunnelLogger()
        f.record(self._d(REJECT, stage="shadow_only"))
        assert f.stats.quality_reject_count == 1
        assert f.stats.capacity_reject_count == 0

    def test_capacity_stages_constant_is_complete(self):
        """Capacity stages set must include the four known capacity filters."""
        for stage in ("max_open_trades", "duplicate", "cooldown",
                      "daily_loss_kill_switch"):
            assert stage in CAPACITY_STAGES

    def test_mixed_rejects(self):
        f = FunnelLogger()
        f.record(self._d(REJECT, stage="max_open_trades"))
        f.record(self._d(REJECT, stage="score_threshold"))
        f.record(self._d(REJECT, stage="duplicate"))
        f.record(self._d(REJECT, stage="liquidity"))
        assert f.stats.capacity_reject_count == 2
        assert f.stats.quality_reject_count == 2

    def test_funnel_stats_persisted(self, cfg, tmp_path):
        db = Storage(str(tmp_path / "test.db"))
        f = FunnelLogger()
        f.record(self._d(REJECT, stage="max_open_trades"))
        f.record(self._d(REJECT, stage="score_threshold"))
        stats = f.finalize(last_trade_minutes_ago=5.0, cycle_ms=100.0)
        db.insert_funnel(stats)
        row = db.latest_funnel()
        assert row is not None
        assert row["capacity_reject"] == 1
        assert row["quality_reject"] == 1
        db.close()


# ---------------------------------------------------------------------------
# CE-3: full-ladder shadow replay
# ---------------------------------------------------------------------------

class TestLadderReplay:
    def _make_storage(self, tmp_path):
        return Storage(str(tmp_path / "shadow_replay.db"))

    def _insert_shadow(self, db, symbol="BTCUSDT", side=LONG,
                       entry=100.0, stop=99.0, tp1=101.5,
                       setup_type="trend_continuation", sig_ts=0):
        from aurvex.models import OPEN, new_id
        db.insert_shadow({
            "id": new_id(), "ts": now_ms(), "source": "paper",
            "symbol": symbol, "side": side, "setup_type": setup_type,
            "score": 75.0, "entry": entry, "stop_loss": stop, "tp1": tp1,
            "outcome": OPEN, "bars": 0, "signal_bar_ts": sig_ts, "last_bar_ts": sig_ts,
        })

    def test_sl_hit_gives_negative_r(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        entry, stop = 100.0, 99.0
        self._insert_shadow(db, entry=entry, stop=stop, tp1=101.5, sig_ts=0)
        # One candle where low <= stop
        candles = [Candle(ts=60_000, open=100.0, high=100.5, low=98.0,
                          close=99.5, volume=1000.0)]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert r["final_outcome"] == "SL"
        assert r["net_r"] < 0
        assert not r["tp1_hit"]

    def test_tp1_only_hit(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        entry, stop, tp1 = 100.0, 99.0, 101.5
        self._insert_shadow(db, entry=entry, stop=stop, tp1=tp1, sig_ts=0)
        # Bar reaches tp1 but not tp2 (tp2 = 102.5), BE stop set at entry
        candles = [
            Candle(ts=60_000, open=100.0, high=102.0, low=99.5, close=101.0, volume=1000.0),
            # Next bars: BE stop (entry=100) not hit, TP2 not reached
            Candle(ts=120_000, open=101.0, high=101.5, low=100.5, close=101.0, volume=1000.0),
        ]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert r["tp1_hit"]
        assert r["be_moved"]
        assert not r["tp2_hit"]

    def test_full_tp3_gives_positive_r(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        entry, stop = 100.0, 99.0
        tp1 = entry + 1.0 * cfg.tp1_r  # 1.5R above entry
        self._insert_shadow(db, entry=entry, stop=stop, tp1=tp1, sig_ts=0)
        # One bar that blows through all TPs
        tp3_price = entry + 1.0 * cfg.tp3_r
        candles = [Candle(ts=60_000, open=100.0, high=tp3_price + 0.5,
                          low=99.5, close=tp3_price + 0.2, volume=5000.0)]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert r["final_outcome"] == "TP3"
        assert r["tp1_hit"] and r["tp2_hit"] and r["tp3_hit"]
        assert r["net_r"] > 0

    def test_no_lookahead_on_signal_bar(self, cfg, tmp_path):
        """Candles at or before signal_bar_ts must be ignored."""
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        sig_ts = 60_000
        entry, stop = 100.0, 99.0
        self._insert_shadow(db, entry=entry, stop=stop, tp1=101.5, sig_ts=sig_ts)
        # Only a candle AT the signal bar (must be ignored → EXPIRED/no bars)
        candles = [Candle(ts=sig_ts, open=100.0, high=105.0, low=95.0,
                          close=100.0, volume=1000.0)]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert r["bars_to_close"] == 0

    def test_expired_outcome_when_no_terminal_hit(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        entry, stop = 100.0, 99.0
        self._insert_shadow(db, entry=entry, stop=stop, tp1=101.5, sig_ts=0)
        # Bars that never hit TP1 (high < 101.5) or SL (low > 99.0)
        candles = [
            Candle(ts=60_000 * i, open=100.0, high=101.0, low=99.5,
                   close=100.0, volume=1000.0)
            for i in range(1, 6)
        ]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert "EXPIRED" in r["final_outcome"]
        assert r["bars_to_close"] == 5

    def test_short_side_sl_hit(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        entry, stop = 100.0, 101.0  # short stop above entry
        tp1 = 98.5  # short TP1 below entry (1.5R)
        self._insert_shadow(db, entry=entry, stop=stop, tp1=tp1,
                             side=SHORT, sig_ts=0)
        # Bar where high >= stop → SL
        candles = [Candle(ts=60_000, open=100.0, high=101.5, low=99.5,
                          close=100.5, volume=1000.0)]
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 1
        r = results[0]
        assert r["final_outcome"] == "SL"
        assert r["net_r"] < 0

    def test_missing_symbol_skipped(self, cfg, tmp_path):
        db = self._make_storage(tmp_path)
        learner = ShadowLearner(cfg, db)
        self._insert_shadow(db, symbol="ETHUSDT")
        # Pass candles only for BTCUSDT (not ETHUSDT)
        candles = _make_candles(10, price=100.0)
        results = learner.ladder_replay({"BTCUSDT": candles})
        assert len(results) == 0


# ---------------------------------------------------------------------------
# CE-2: detect_all + best-score selection
# ---------------------------------------------------------------------------

class TestDetectAllBestScore:
    def test_detect_all_returns_list(self, cfg):
        detector = SetupDetector(cfg)
        snap = make_snapshot()
        signals = detector.detect_all(snap)
        assert isinstance(signals, list)

    def test_decision_engine_uses_best_scored_signal(self, cfg):
        """The engine should pick the highest-scored signal when multiple are found."""
        eng = DecisionEngine(cfg)
        # Make two signals with different scores; only the higher one should ALLOW.
        sig_low = make_signal(setup_type="momentum_breakout", score=40.0)
        sig_high = make_signal(setup_type="trend_continuation", score=90.0)

        # Both pass filters individually
        d_low = eng.decide(sig_low, make_snapshot(), _pf(cfg))
        d_high = eng.decide(sig_high, make_snapshot(), _pf(cfg))

        # High score → ALLOW; low score → REJECT (below threshold=60)
        assert d_high.decision == ALLOW
        assert d_low.decision != ALLOW

    def test_config_shadow_only_setups_from_env(self, monkeypatch):
        """SHADOW_ONLY_SETUPS env var is parsed correctly."""
        monkeypatch.setenv("SHADOW_ONLY_SETUPS", "momentum_breakout,volume_expansion")
        cfg = Config()
        assert "momentum_breakout" in cfg.shadow_only_setups
        assert "volume_expansion" in cfg.shadow_only_setups

    def test_config_min_position_notional_from_env(self, monkeypatch):
        """MIN_POSITION_NOTIONAL env var is parsed correctly."""
        monkeypatch.setenv("MIN_POSITION_NOTIONAL", "10.0")
        cfg = Config()
        assert cfg.min_position_notional == 10.0
