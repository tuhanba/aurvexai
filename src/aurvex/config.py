"""
Central configuration for AurvexAI clean-core scalp engine.

Every tunable parameter lives here and is overridable via environment
variables (loaded from a local .env file if present). NO SECRETS are
hard-coded; secrets are read from the environment only.

Design rule: paper mode and live mode share *all* of these values.
The ONLY thing that differs between paper and live is the executor and
the live execution-safety layer (see execution).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# .env loading (optional dependency; falls back to plain os.environ)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _str(key: str, default: str) -> str:
    v = os.getenv(key)
    return v if v is not None and v != "" else default


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on", "y"}


def _list(key: str, default: List[str]) -> List[str]:
    v = os.getenv(key)
    if not v:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class Config:
    # -- Mode --------------------------------------------------------------
    # AX_MODE: "paper" (default) or "live". Live also REQUIRES the explicit
    # live-readiness gate to be opened (see LIVE_ENABLED). Defaulting to
    # paper is a deliberate safety choice.
    mode: str = field(default_factory=lambda: _str("AX_MODE", "paper").lower())

    # -- Market / exchange -------------------------------------------------
    exchange_id: str = field(default_factory=lambda: _str("EXCHANGE_ID", "binanceusdm"))
    quote_asset: str = field(default_factory=lambda: _str("QUOTE_ASSET", "USDT"))
    ltf: str = field(default_factory=lambda: _str("LTF", "1m"))   # trigger timeframe
    htf: str = field(default_factory=lambda: _str("HTF", "15m"))  # context timeframe
    ltf_limit: int = field(default_factory=lambda: _int("LTF_LIMIT", 120))
    htf_limit: int = field(default_factory=lambda: _int("HTF_LIMIT", 60))
    orderbook_depth: int = field(default_factory=lambda: _int("ORDERBOOK_DEPTH", 20))

    # Data provider: "ccxt" (real Binance public data) or "synthetic" (offline
    # deterministic generator for tests / local demo with no network).
    data_provider: str = field(default_factory=lambda: _str("DATA_PROVIDER", "ccxt"))

    # -- Universe scanner --------------------------------------------------
    universe_size: int = field(default_factory=lambda: _int("UNIVERSE_SIZE", 40))
    min_quote_volume_24h: float = field(
        default_factory=lambda: _float("MIN_QUOTE_VOLUME_24H", 50_000_000.0)
    )
    # Hard include / exclude lists (symbols like "BTC/USDT:USDT").
    universe_include: List[str] = field(default_factory=lambda: _list("UNIVERSE_INCLUDE", []))
    universe_exclude: List[str] = field(default_factory=lambda: _list("UNIVERSE_EXCLUDE", []))

    # -- Thresholds (single source of truth, paper == live) ----------------
    trade_threshold: float = field(default_factory=lambda: _float("TRADE_THRESHOLD", 60.0))
    watchlist_threshold: float = field(default_factory=lambda: _float("WATCHLIST_THRESHOLD", 50.0))

    # -- Filters (minimal hard veto) --------------------------------------
    max_spread_pct: float = field(default_factory=lambda: _float("MAX_SPREAD_PCT", 0.06))
    max_slippage_pct: float = field(default_factory=lambda: _float("MAX_SLIPPAGE_PCT", 0.08))

    # -- Risk model --------------------------------------------------------
    risk_pct: float = field(default_factory=lambda: _float("RISK_PCT", 0.5))   # % of balance per trade
    max_open_trades: int = field(default_factory=lambda: _int("MAX_OPEN_TRADES", 4))
    max_daily_loss_pct: float = field(default_factory=lambda: _float("MAX_DAILY_LOSS_PCT", 3.0))
    max_portfolio_exposure_pct: float = field(
        default_factory=lambda: _float("MAX_PORTFOLIO_EXPOSURE_PCT", 200.0)
    )
    max_leverage: int = field(default_factory=lambda: _int("MAX_LEVERAGE", 10))
    coin_cooldown_minutes: float = field(default_factory=lambda: _float("COIN_COOLDOWN_MINUTES", 20.0))

    # Stop-distance guards (as fraction of price).
    min_stop_dist_pct: float = field(default_factory=lambda: _float("MIN_STOP_DIST_PCT", 0.30))
    max_stop_dist_pct: float = field(default_factory=lambda: _float("MAX_STOP_DIST_PCT", 2.50))

    # Take-profit R multiples (SL distance == 1R).
    tp1_r: float = field(default_factory=lambda: _float("TP1_R", 1.5))
    tp2_r: float = field(default_factory=lambda: _float("TP2_R", 2.5))
    tp3_r: float = field(default_factory=lambda: _float("TP3_R", 4.0))
    # Scale-out fractions at TP1/TP2/TP3 (must sum to 1.0).
    tp1_frac: float = field(default_factory=lambda: _float("TP1_FRAC", 0.5))
    tp2_frac: float = field(default_factory=lambda: _float("TP2_FRAC", 0.3))
    tp3_frac: float = field(default_factory=lambda: _float("TP3_FRAC", 0.2))
    move_sl_to_be_after_tp1: bool = field(
        default_factory=lambda: _bool("MOVE_SL_TO_BE_AFTER_TP1", True)
    )

    # -- Fees / slippage assumptions (taker, one side) ---------------------
    taker_fee_pct: float = field(default_factory=lambda: _float("TAKER_FEE_PCT", 0.045))
    slippage_assumption_pct: float = field(
        default_factory=lambda: _float("SLIPPAGE_ASSUMPTION_PCT", 0.02)
    )

    # -- Paper account -----------------------------------------------------
    initial_paper_balance: float = field(
        default_factory=lambda: _float("INITIAL_PAPER_BALANCE", 1000.0)
    )

    # -- Engine loop -------------------------------------------------------
    cycle_interval_sec: float = field(default_factory=lambda: _float("CYCLE_INTERVAL_SEC", 20.0))
    max_symbols_per_cycle: int = field(default_factory=lambda: _int("MAX_SYMBOLS_PER_CYCLE", 40))

    # -- Shadow learner ----------------------------------------------------
    shadow_min_score: float = field(default_factory=lambda: _float("SHADOW_MIN_SCORE", 45.0))
    shadow_max_bars: int = field(default_factory=lambda: _int("SHADOW_MAX_BARS", 120))
    # Observe-first: when False the learner only watches and reports; advisory
    # score nudges are NOT fed back into scoring. Never enables a hard veto.
    shadow_apply: bool = field(default_factory=lambda: _bool("SHADOW_APPLY", False))

    # -- Storage -----------------------------------------------------------
    db_path: str = field(default_factory=lambda: _str("DB_PATH", "data/aurvex.db"))

    # -- Dashboard ---------------------------------------------------------
    dashboard_host: str = field(default_factory=lambda: _str("DASHBOARD_HOST", "0.0.0.0"))
    dashboard_port: int = field(default_factory=lambda: _int("DASHBOARD_PORT", 5000))

    # -- Telegram (secrets via env only) -----------------------------------
    telegram_enabled: bool = field(default_factory=lambda: _bool("TELEGRAM_ENABLED", True))
    telegram_bot_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _str("TELEGRAM_CHAT_ID", ""))

    # -- Live safety gate --------------------------------------------------
    # LIVE_ENABLED must be explicitly true AND a human confirmation token set
    # for the live executor to even *attempt* (it still never sends real
    # orders in this build - the order call is a stub).
    live_enabled: bool = field(default_factory=lambda: _bool("LIVE_ENABLED", False))
    live_human_confirm: str = field(default_factory=lambda: _str("LIVE_HUMAN_CONFIRM", ""))
    live_canary_risk_pct: float = field(default_factory=lambda: _float("LIVE_CANARY_RISK_PCT", 0.1))
    live_order_timeout_sec: float = field(default_factory=lambda: _float("LIVE_ORDER_TIMEOUT_SEC", 5.0))
    live_max_retries: int = field(default_factory=lambda: _int("LIVE_MAX_RETRIES", 2))

    # -- Logging -----------------------------------------------------------
    log_level: str = field(default_factory=lambda: _str("LOG_LEVEL", "INFO"))

    # ---------------------------------------------------------------------
    def validate(self) -> None:
        frac_sum = self.tp1_frac + self.tp2_frac + self.tp3_frac
        assert abs(frac_sum - 1.0) < 1e-6, f"TP fractions must sum to 1.0 (got {frac_sum})"
        assert self.trade_threshold >= self.watchlist_threshold, (
            "trade_threshold must be >= watchlist_threshold"
        )
        assert 0 < self.risk_pct <= 5, "risk_pct out of sane range"
        assert self.mode in {"paper", "live"}, "AX_MODE must be 'paper' or 'live'"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


# Convenience singleton-style accessor (callers may also instantiate their own).
def load_config() -> Config:
    cfg = Config()
    cfg.validate()
    return cfg
