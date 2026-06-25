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


def _int_list(key: str, default: List[int]) -> List[int]:
    v = os.getenv(key)
    if not v:
        return list(default)
    result = []
    for x in v.split(","):
        x = x.strip()
        if x:
            try:
                result.append(int(x))
            except ValueError:
                pass
    return result


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

    # -- Leverage / margin model -------------------------------------------
    # Maintenance margin rate used to estimate the liquidation price. Set this
    # conservatively at or above the exchange's tier-1 rate for the traded
    # symbols (Binance USDT-M tier-1 is ~0.4-1.0%). Higher = safer (further
    # from the modelled liquidation, lower allowed leverage).
    maint_margin_rate: float = field(default_factory=lambda: _float("MAINT_MARGIN_RATE", 0.005))
    # The estimated liquidation move must be at least this multiple of the stop
    # distance away from entry. >= 1.0; 2.0 means "liquidation must be twice as
    # far as the stop". This is the hard guarantee that the stop fires first.
    liq_safety_buffer: float = field(default_factory=lambda: _float("LIQ_SAFETY_BUFFER", 2.0))
    # Fraction of balance kept free (un-committed as margin) as a buffer. The
    # remainder is spread across the still-open slots to pick a slot-aware target
    # margin, so one tight-stop trade can't hog the whole book. 0-90.
    free_margin_reserve_pct: float = field(
        default_factory=lambda: _float("FREE_MARGIN_RESERVE_PCT", 20.0)
    )

    # Stop-distance guards (as fraction of price).
    min_stop_dist_pct: float = field(default_factory=lambda: _float("MIN_STOP_DIST_PCT", 0.30))
    max_stop_dist_pct: float = field(default_factory=lambda: _float("MAX_STOP_DIST_PCT", 2.50))
    # Extended stop ceiling for bugra_replica profile (fixed-% wider stop).
    max_stop_dist_pct_bugra: float = field(
        default_factory=lambda: _float("MAX_STOP_DIST_PCT_BUGRA", 5.00)
    )

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
    # 8-hour perpetual funding rate applied as a holding cost in the backtester
    # so OOS expectancy is net of fee+slippage+funding (Block 6). 0.0 = disabled
    # (default; offline synthetic data carries no real funding). Real-data runs
    # set this to the observed/typical rate, e.g. 0.0001 (0.01% per 8h).
    funding_rate_8h: float = field(default_factory=lambda: _float("FUNDING_RATE_8H", 0.0))

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
    # CE-1: setups restricted to shadow observation only (never traded).
    # Comma-separated setup_type names, e.g. "momentum_breakout,volume_expansion".
    # These setups still score and track in shadow — only execution is blocked.
    shadow_only_setups: List[str] = field(
        default_factory=lambda: _list("SHADOW_ONLY_SETUPS", [])
    )

    # -- Leverage policy ---------------------------------------------------
    # "efficient"   : use the highest liquidation-safe leverage to minimise
    #                 locked margin (same risk, less capital committed).
    # "conservative": original slot-fit minimum leverage (legacy behaviour).
    leverage_policy: str = field(
        default_factory=lambda: _str("LEVERAGE_POLICY", "efficient")
    )

    # -- Runner / trailing stop --------------------------------------------
    # runner_frac: fraction of position kept as a "runner" after TP3, trailed.
    # 0.0 = disabled (legacy). Must satisfy tp1+tp2+tp3+runner == 1.0 when > 0.
    runner_frac: float = field(default_factory=lambda: _float("RUNNER_FRAC", 0.0))
    # trail_mode: how to advance the trailing stop for the runner.
    # "atr"         : close ∓ trail_atr_mult * ATR14
    # "supertrend"  : supertrend line
    # "kijun"       : Ichimoku kijun-sen (base line)
    # "swing"       : N-bar micro swing high/low
    trail_mode: str = field(default_factory=lambda: _str("TRAIL_MODE", "atr"))
    trail_atr_mult: float = field(default_factory=lambda: _float("TRAIL_ATR_MULT", 0.7))
    trail_swing_bars: int = field(default_factory=lambda: _int("TRAIL_SWING_BARS", 5))

    # -- Strategy profile ---------------------------------------------------
    # "aurvex_enhanced": enhanced profile — same TA core + ATR-adaptive SL (default)
    # "bugra_replica"  : Bugra system replica — same 5-condition TA, fixed-% SL/TP
    strategy_profile: str = field(
        default_factory=lambda: _str("STRATEGY_PROFILE", "aurvex_enhanced")
    )

    # -- Bugra replica parameters ------------------------------------------
    bugra_stop_pct: float = field(default_factory=lambda: _float("BUGRA_STOP_PCT", 4.49))
    bugra_tp1_pct: float = field(default_factory=lambda: _float("BUGRA_TP1_PCT", 1.50))
    bugra_tp2_pct: float = field(default_factory=lambda: _float("BUGRA_TP2_PCT", 2.80))
    bugra_tp3_pct: float = field(default_factory=lambda: _float("BUGRA_TP3_PCT", 4.49))
    bugra_ema_fast: int = field(default_factory=lambda: _int("BUGRA_EMA_FAST", 9))
    bugra_ema_slow: int = field(default_factory=lambda: _int("BUGRA_EMA_SLOW", 21))
    bugra_st_period: int = field(default_factory=lambda: _int("BUGRA_ST_PERIOD", 10))
    bugra_st_mult: float = field(default_factory=lambda: _float("BUGRA_ST_MULT", 3.0))
    bugra_adx_min: float = field(default_factory=lambda: _float("BUGRA_ADX_MIN", 20.0))

    # CE-2 (Wave 2): allowed UTC trade hours, e.g. "10,11,12,13".
    # Empty list = all hours allowed (default). Filters out dead / toksik sessions
    # (Asya gece saatleri, ABD cash-open whipsaw). Forward-test before enabling.
    trade_hours_utc: List[int] = field(
        default_factory=lambda: _int_list("TRADE_HOURS_UTC", [])
    )

    # -- W3-T4: Score validity gate ----------------------------------------
    # When True (default), score < trade_threshold is a hard REJECT gate (current
    # behaviour). When False, score is advisory; signals proceed to risk/ranking.
    # T4 decision: N too thin at measurement time → keep True.
    score_as_gate: bool = field(default_factory=lambda: _bool("SCORE_AS_GATE", True))

    # -- W3-T5: Global two-pass ranking + allocation -----------------------
    # When False (default), the engine's inline first-come allocation runs
    # byte-identical to pre-T5. Set True to activate rank-order allocation.
    global_ranking: bool = field(default_factory=lambda: _bool("GLOBAL_RANKING", False))
    # Rank key: "score" (raw score) | "composite" (score + shadow advisory delta).
    rank_key: str = field(default_factory=lambda: _str("RANK_KEY", "composite"))
    # Max concurrent slots in one correlation cluster. 0 = disabled.
    max_per_cluster: int = field(default_factory=lambda: _int("MAX_PER_CLUSTER", 0))
    # Max concurrent cluster notional as % of equity. 0 = disabled.
    max_cluster_exposure_pct: float = field(
        default_factory=lambda: _float("MAX_CLUSTER_EXPOSURE_PCT", 0.0)
    )
    # Max concurrent open trades per side (LONG or SHORT). 0 = disabled.
    max_same_side: int = field(default_factory=lambda: _int("MAX_SAME_SIDE", 0))

    # CE-5 (Wave 2): minimum HTF ADX required for trend_continuation setup.
    # 0.0 = gate disabled (default, backward-compatible). Set e.g. 20.0 to gate
    # out chop-days where trend_continuation signal quality is lowest.
    min_htf_adx_trend: float = field(
        default_factory=lambda: _float("MIN_HTF_ADX_TREND", 0.0)
    )

    # -- Risk model (IF-2) -------------------------------------------------
    # Minimum position notional in quote currency. Trades sized below this
    # threshold (e.g. stub trades from tight exposure-cap room) are rejected
    # rather than wasting a slot on a micro position.
    min_position_notional: float = field(
        default_factory=lambda: _float("MIN_POSITION_NOTIONAL", 5.0)
    )

    # -- Epoch label -------------------------------------------------------
    # Written once into the DB meta on first start (ensure_epoch). Change this
    # value + run `python main.py reset` to start a clean forward-test epoch
    # while preserving all shadow history.
    epoch_label: str = field(default_factory=lambda: _str("EPOCH_LABEL", "wave3"))

    # -- Storage -----------------------------------------------------------
    db_path: str = field(default_factory=lambda: _str("DB_PATH", "data/aurvex.db"))

    # -- Dashboard ---------------------------------------------------------
    # IF-1: default 0.0.0.0 (all interfaces). For production security bind
    # to 127.0.0.1 via DASHBOARD_HOST env var and access through SSH tunnel
    # or a reverse proxy with auth/HTTPS.
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
        frac_sum = self.tp1_frac + self.tp2_frac + self.tp3_frac + self.runner_frac
        assert abs(frac_sum - 1.0) < 1e-6, (
            f"TP fractions (tp1+tp2+tp3+runner) must sum to 1.0 (got {frac_sum})"
        )
        assert self.trade_threshold >= self.watchlist_threshold, (
            "trade_threshold must be >= watchlist_threshold"
        )
        assert 0 < self.risk_pct <= 5, "risk_pct out of sane range"
        assert self.mode in {"paper", "live"}, "AX_MODE must be 'paper' or 'live'"
        assert self.strategy_profile in {"bugra_replica", "aurvex_enhanced"}, (
            "STRATEGY_PROFILE must be bugra_replica|aurvex_enhanced"
        )
        assert self.leverage_policy in {"efficient", "conservative"}, (
            "LEVERAGE_POLICY must be efficient|conservative"
        )
        assert self.maint_margin_rate >= 0, "maint_margin_rate must be >= 0"
        assert self.liq_safety_buffer >= 1.0, "liq_safety_buffer must be >= 1.0"
        assert self.max_leverage >= 1, "max_leverage must be >= 1"
        assert 0.0 <= self.free_margin_reserve_pct <= 90.0, (
            "free_margin_reserve_pct must be in [0, 90]"
        )

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


# Convenience singleton-style accessor (callers may also instantiate their own).
def load_config() -> Config:
    cfg = Config()
    cfg.validate()
    return cfg
