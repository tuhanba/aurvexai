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

    # Test hermeticity: when AURVEX_NO_DOTENV=1 (set by the test conftest) the
    # deployment's .env must NOT leak into unit tests (e.g. a server-side
    # SHADOW_ONLY_SETUPS would otherwise make every test setup shadow-only).
    if os.environ.get("AURVEX_NO_DOTENV") != "1":
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


# ---------------------------------------------------------------------------
# Named risk profiles (config-only)
# ---------------------------------------------------------------------------
# A profile supplies the DEFAULTS for a few account-level knobs (balance,
# risk %, risk band, daily-loss limit, slots, dashboard port). An explicit
# environment variable ALWAYS wins over the profile default, so a deployment can
# fine-tune any single knob without abandoning the profile.
#
# Profiles change only the sizing INPUTS (balance, risk_pct, daily-loss budget);
# they NEVER touch DecisionEngine.decide()'s allow/reject logic. Paper/live/
# backtest parity is preserved because the executors all read the same Config.
#
#   aggressive_paper  (DEFAULT for the new epoch): 200 / 2% / 1-3% band / 10%
#   conservative_paper (legacy paper defaults)   : 1000 / 0.5% / 0.25-1% / 3%
_PROFILE_DEFAULTS: dict = {
    "conservative_paper": {
        "INITIAL_PAPER_BALANCE": 1000.0,
        "RISK_PCT": 0.5,
        "MIN_RISK_PCT": 0.25,
        "MAX_RISK_PCT": 1.0,
        "MAX_DAILY_LOSS_PCT": 3.0,
        "DAILY_PROFIT_LOCK_PCT": 10.0,
        "MAX_OPEN_TRADES": 4,
        "DASHBOARD_PORT": 5000,
    },
    "aggressive_paper": {
        "INITIAL_PAPER_BALANCE": 200.0,
        "RISK_PCT": 2.0,
        "MIN_RISK_PCT": 1.0,
        "MAX_RISK_PCT": 3.0,
        "MAX_DAILY_LOSS_PCT": 10.0,
        "DAILY_PROFIT_LOCK_PCT": 10.0,
        "MAX_OPEN_TRADES": 4,
        "DASHBOARD_PORT": 5000,
    },
    # Maximum aggression the MEASURED edge survives (owner-requested,
    # 2026-07-09). Risk 3% = the donchian max-eff study's winning multiplier
    # (+19% growth, DD ~20->30% band); 6 slots; profit lock raised to 20% so
    # big runner days are not capped early. The kill switch stays 10% — it is
    # the ruin guard, never a tunable. Expectation at the validated numbers:
    # ~0.75-1%/day compounding with ~30-40% drawdowns and losing WEEKS.
    # Anything promising more per-day than this is sizing into ruin.
    "aggressive_plus": {
        "INITIAL_PAPER_BALANCE": 200.0,
        "RISK_PCT": 3.0,
        "MIN_RISK_PCT": 1.5,
        "MAX_RISK_PCT": 4.0,
        "MAX_DAILY_LOSS_PCT": 10.0,
        "DAILY_PROFIT_LOCK_PCT": 20.0,
        "MAX_OPEN_TRADES": 6,
        "DASHBOARD_PORT": 5000,
    },
}
_DEFAULT_RISK_PROFILE = "aggressive_paper"


def _active_profile() -> str:
    p = _str("RISK_PROFILE", _DEFAULT_RISK_PROFILE).strip().lower()
    return p if p in _PROFILE_DEFAULTS else _DEFAULT_RISK_PROFILE


def _profile_default(key: str):
    return _PROFILE_DEFAULTS[_active_profile()][key]


def _pfloat(key: str) -> float:
    """Profile-aware float: an explicit env value wins, else the profile default."""
    v = os.getenv(key)
    if v is not None and v != "":
        try:
            return float(v)
        except ValueError:
            pass
    return float(_profile_default(key))


def _pint(key: str) -> int:
    """Profile-aware int: an explicit env value wins, else the profile default."""
    v = os.getenv(key)
    if v is not None and v != "":
        try:
            return int(v)
        except ValueError:
            pass
    return int(_profile_default(key))


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

    # Closed-bar-aware kline cache (ccxt provider): a timeframe's CLOSED view
    # can only change when a new bar closes, so klines are refetched only when
    # a new bar can exist. Parity-safe (identical decision inputs), removes
    # most per-cycle REST calls at 4h/1d. false = legacy fetch-every-cycle.
    kline_cache_enabled: bool = field(
        default_factory=lambda: _bool("KLINE_CACHE_ENABLED", True))
    # Universe re-rank interval (sec). fetch_tickers is the heaviest public
    # call and volume ranks don't move minute-to-minute; the pinned
    # UNIVERSE_INCLUDE deployment barely uses the ranking at all. 0 = every cycle.
    universe_refresh_sec: int = field(
        default_factory=lambda: _int("UNIVERSE_REFRESH_SEC", 600))

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

    # -- Risk profile (config-only; supplies the defaults below) ------------
    # conservative_paper | aggressive_paper. Default aggressive_paper for the
    # new epoch. Explicit env vars below always override the profile default.
    risk_profile: str = field(default_factory=_active_profile)

    # -- Risk model --------------------------------------------------------
    risk_pct: float = field(default_factory=lambda: _pfloat("RISK_PCT"))   # % of balance per trade
    # Risk band: sizing-relevant floor/ceiling for the per-trade risk %. The
    # active risk_pct must sit within [min_risk_pct, max_risk_pct] (validated).
    min_risk_pct: float = field(default_factory=lambda: _pfloat("MIN_RISK_PCT"))
    max_risk_pct: float = field(default_factory=lambda: _pfloat("MAX_RISK_PCT"))
    max_open_trades: int = field(default_factory=lambda: _pint("MAX_OPEN_TRADES"))
    max_daily_loss_pct: float = field(default_factory=lambda: _pfloat("MAX_DAILY_LOSS_PCT"))
    # Daily profit lock (mirror of the daily-loss kill switch, profit side):
    # once today's UTC REALIZED PnL reaches balance * pct/100, new entries are
    # rejected (reason "daily_profit_lock"). Open trades keep their normal exit
    # management; the lock resets automatically at UTC day rollover.
    daily_profit_lock_enabled: bool = field(
        default_factory=lambda: _bool("DAILY_PROFIT_LOCK_ENABLED", True))
    daily_profit_lock_pct: float = field(
        default_factory=lambda: _pfloat("DAILY_PROFIT_LOCK_PCT"))
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
    # Time-stop: force-close a trade that has been open >= this many LTF bars
    # without hitting TP/SL, at the bar close (exit reason "TIME"). 0 = disabled
    # (DEFAULT — preserves parity: no profile changes hold behaviour unless this
    # is set). Needed for the reversion "clean shot" (Phase 4): a mean-reversion
    # bounce that never reverts should be cut, not ridden to the window force-close.
    # Only active on the backtest/replay/engine path (callers that pass bar_ts);
    # legacy fill callers without a bar timestamp are unaffected.
    time_stop_bars: int = field(default_factory=lambda: _int("TIME_STOP_BARS", 0))

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
        default_factory=lambda: _pfloat("INITIAL_PAPER_BALANCE")
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
    # "reversion_v1"   : additive mean-reversion entry (Bollinger stretch + ranging
    #                    LTF + oversold/overbought RSI); maker-friendly fixed-% SL
    #                    and a single quick R-multiple TP. Never fires under the
    #                    momentum profiles; see SCALP_STRATEGY_SPEC / setups.py.
    # "squeeze_breakout": volatility-squeeze breakout (edge-search campaign
    #                    2026-07-05 candidate): W-bar range in its lowest Qth
    #                    percentile + close breaks the W-bar high/low. Stop =
    #                    1× range; exit = stop or TIME_STOP_BARS time-stop (no
    #                    profit target by design — validated exit shape).
    #                    Intended deployment: LTF=1h, HTF=4h, LTF_LIMIT>=520,
    #                    TIME_STOP_BARS=48.
    strategy_profile: str = field(
        default_factory=lambda: _str("STRATEGY_PROFILE", "aurvex_enhanced")
    )

    # Multi-strategy mode. When STRATEGIES is set, the engine runs SEVERAL
    # strategies on ONE shared account/balance/DB — one kill switch, one profit
    # lock, one exposure cap, one slot pool — each strategy entering on its own
    # timeframe and exiting by its own rule. Empty (default) = single-strategy
    # mode governed by STRATEGY_PROFILE, byte-identical to before.
    #
    # Format: space- or comma-separated specs "profile@ltf/htf[:ts=N][:ch=N]"
    #   ts = per-strategy time_stop_bars, ch = per-strategy channel-exit bars.
    # Example (the validated pairing):
    #   STRATEGIES="donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    strategies: str = field(default_factory=lambda: _str("STRATEGIES", ""))

    # -- Mean-reversion (reversion_v1) parameters --------------------------
    # Additive, independent of the momentum knobs. These fields always exist
    # (cheap defaults) but only the reversion setup + its exit branch read them,
    # so a non-reversion run is byte-identical to before. The exit is a single
    # quick TP at REV_TP_R taking 100% (snap-and-out: no break-even move, no
    # runner) — structurally enforced in RiskManager._build_targets.
    rev_bb_n: int = field(default_factory=lambda: _int("REV_BB_N", 20))
    rev_bb_k: float = field(default_factory=lambda: _float("REV_BB_K", 2.0))
    rev_adx_max: float = field(default_factory=lambda: _float("REV_ADX_MAX", 22.0))
    rev_htf_adx_max: float = field(
        default_factory=lambda: _float("REV_HTF_ADX_MAX", 25.0))
    rev_rsi_long: float = field(default_factory=lambda: _float("REV_RSI_LONG", 30.0))
    rev_rsi_short: float = field(default_factory=lambda: _float("REV_RSI_SHORT", 70.0))
    rev_sl_pct: float = field(default_factory=lambda: _float("REV_SL_PCT", 1.5))
    rev_tp_r: float = field(default_factory=lambda: _float("REV_TP_R", 1.2))

    # -- Squeeze-breakout (squeeze_breakout) parameters ---------------------
    # Faithful to the validated research rules (EDGE_SEARCH_2026-07-05.md
    # Phase-2, family 3): 24-bar range squeeze at the 20th percentile of a
    # trailing <=500-range baseline, breakout close beyond the 24-bar
    # high/low, stop one full range away, no profit target (SQZ_TP_R is an
    # unreachable sentinel that keeps the 3-slot TP contract), exit via
    # TIME_STOP_BARS. Only the squeeze setup + its risk branches read these.
    sqz_window: int = field(default_factory=lambda: _int("SQZ_WINDOW", 24))
    sqz_pctile: float = field(default_factory=lambda: _float("SQZ_PCTILE", 20.0))
    sqz_baseline: int = field(default_factory=lambda: _int("SQZ_BASELINE", 500))
    sqz_stop_mult: float = field(default_factory=lambda: _float("SQZ_STOP_MULT", 1.0))
    sqz_tp_r: float = field(default_factory=lambda: _float("SQZ_TP_R", 1000.0))
    max_stop_dist_pct_sqz: float = field(
        default_factory=lambda: _float("MAX_STOP_DIST_PCT_SQZ", 10.0))
    # Refinement grid 2026-07-05: requiring the breakout to align with the
    # LTF 200-bar SMA trend improved BOTH split halves (+0.166/+0.105R vs
    # +0.118/+0.077R baseline). Default ON (harness-confirmed).
    sqz_trend_filter: bool = field(
        default_factory=lambda: _bool("SQZ_TREND_FILTER", True))

    # -- Donchian trend (donchian_trend) parameters -------------------------
    # Edge-search 2026-07-05, strongest family (+0.27-0.46R/trade, all 4h
    # cells positive in both split halves). Entry: close breaks the N-bar
    # channel; initial stop 2xATR(14); exit when the close breaks the X-bar
    # opposite channel (streaming state in the executor) — no profit target
    # (DON_TP_R sentinel keeps the 3-slot TP contract). Deploy: LTF=4h
    # HTF=1d TIME_STOP_BARS=0.
    don_entry_bars: int = field(default_factory=lambda: _int("DON_ENTRY_BARS", 20))
    don_exit_bars: int = field(default_factory=lambda: _int("DON_EXIT_BARS", 20))
    don_atr_mult: float = field(default_factory=lambda: _float("DON_ATR_MULT", 2.0))
    don_tp_r: float = field(default_factory=lambda: _float("DON_TP_R", 1000.0))
    max_stop_dist_pct_don: float = field(
        default_factory=lambda: _float("MAX_STOP_DIST_PCT_DON", 12.0))

    # -- Ichimoku trend (ichimoku_trend profile) ----------------------------
    # I1 TK-cross "strong": Tenkan(9) x Kijun(26) cross while price is on the
    # matching side of the displaced cloud (spans from bars <= i-26). Exit =
    # opposite TK cross (streaming, close-based) or the stop; no TP by design
    # (ICH_TP_R sentinel keeps the 3-slot TP contract). Validated @4h only.
    ich_atr_mult: float = field(default_factory=lambda: _float("ICH_ATR_MULT", 2.0))
    ich_tp_r: float = field(default_factory=lambda: _float("ICH_TP_R", 1000.0))
    max_stop_dist_pct_ich: float = field(
        default_factory=lambda: _float("MAX_STOP_DIST_PCT_ICH", 12.0))

    # -- Telegram periodic open-position summary -----------------------------
    # Every TG_POS_SUMMARY_MIN minutes (default 60; 0 disables) the engine
    # sends a compact open-positions digest: per trade uPnL (USDT/R/%), plus
    # equity and today's realised PnL. Sent only when positions are open.
    # Pure notification — reads the same marks the dashboard uses.
    tg_pos_summary_min: int = field(
        default_factory=lambda: _int("TG_POS_SUMMARY_MIN", 60))
    # Stop-approach alert: one Telegram warning per trade when the live mark
    # has consumed all but TG_STOP_ALERT_ROOM_PCT % of the entry->stop
    # distance (default 25; 0 disables). Display/notify only.
    tg_stop_alert_room_pct: float = field(
        default_factory=lambda: _float("TG_STOP_ALERT_ROOM_PCT", 25.0))
    # Daily-loss budget alerts: one warning each when today's realised loss
    # crosses these %s of the kill-switch budget (empty disables).
    tg_loss_budget_alerts: List[float] = field(
        default_factory=lambda: [float(x) for x in
                                 _list("TG_LOSS_BUDGET_ALERTS", ["50", "80"])])
    # Weekly per-strategy report (Sunday 18:00 UTC): 1 = on, 0 = off.
    tg_weekly_report: bool = field(
        default_factory=lambda: _bool("TG_WEEKLY_REPORT", True))
    # Quiet hours "HH-HH" UTC (e.g. "0-7"): routine messages (digests,
    # summaries, trade events) are suppressed; CRITICAL ones (kill switch,
    # stop-approach, budget alerts, live-gate) always deliver. "" = off.
    tg_quiet_hours: str = field(
        default_factory=lambda: _str("TG_QUIET_HOURS", ""))

    # -- Band-walk continuation (band_walk profile) --------------------------
    # Campaign-7 F3 (CONDITIONAL_TA_WAVE_REPORT.md): two consecutive closes
    # outside BB(BW_BB_N, BW_BB_K) with ADX(14) rising over BW_ADX_LOOK bars →
    # enter with the walk. Stop BW_ATR_MULT × ATR(14); exit = stop or the
    # generic time-stop (researched shape: ts=12 @4h); no TP by design
    # (BW_TP_R sentinel keeps the 3-slot TP contract).
    bw_bb_n: int = field(default_factory=lambda: _int("BW_BB_N", 20))
    bw_bb_k: float = field(default_factory=lambda: _float("BW_BB_K", 2.0))
    bw_adx_look: int = field(default_factory=lambda: _int("BW_ADX_LOOK", 3))
    bw_atr_mult: float = field(default_factory=lambda: _float("BW_ATR_MULT", 2.0))
    bw_tp_r: float = field(default_factory=lambda: _float("BW_TP_R", 1000.0))
    max_stop_dist_pct_bw: float = field(
        default_factory=lambda: _float("MAX_STOP_DIST_PCT_BW", 12.0))

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

    # -- Buğra primary gate: score is SUPPORT, not a veto ------------------
    # When False (DEFAULT), score is advisory only: a Buğra signal that passes
    # the safety filters + risk gate is ALLOWED regardless of score. Score then
    # acts as a SUPPORT layer (ranking + risk modulation), never a hard block.
    # When True (legacy), score < trade_threshold is a hard REJECT/WATCH gate.
    # Default flipped to False because score predictivity is UNCONFIRMED in
    # clean-core (epoch N too thin to prove monotonicity) — an unvalidated score
    # must not veto Buğra, the actual strategy. Env override SCORE_AS_GATE=true
    # reverts to the gated behaviour in one step.
    score_as_gate: bool = field(default_factory=lambda: _bool("SCORE_AS_GATE", False))
    # Optional soft execution floor (default 0.0 = OFF, honouring "no veto").
    # When > 0, a Buğra candidate with score < min_execution_score is rejected
    # with failed_stage="min_score_floor". Exists only as a future safety knob;
    # default leaves Buğra as the sole entry gate.
    min_execution_score: float = field(
        default_factory=lambda: _float("MIN_EXECUTION_SCORE", 0.0)
    )

    # -- Buğra primary gate: two-pass ranking is the slot-selection layer ---
    # When True (DEFAULT now), the engine runs the two-pass rank allocator so the
    # best executable candidates win the limited max_open_trades slots. When
    # False (legacy), the inline first-come loop runs byte-identical to pre-T5.
    global_ranking: bool = field(default_factory=lambda: _bool("GLOBAL_RANKING", True))
    # Rank key:
    #   "edge"      → edge-validated rank (DEFAULT): follows MEASURED edge
    #                 (score-bucket avg_r); falls back to a neutral tiebreak when
    #                 data is thin. Never assumes high score = good.
    #   "composite" → score + shadow advisory delta (capped ±5) [legacy].
    #   "score"     → raw signal score [legacy, for A/B comparison].
    rank_key: str = field(default_factory=lambda: _str("RANK_KEY", "edge"))
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

    # -- Buğra primary gate: score/shadow → risk modulation (SUPPORT) ------
    # When False (DEFAULT), risk_multiplier is forced to 1.0 → sizing is
    # byte-identical to today (the T1 golden tests stay green). When True, the
    # engine modulates the risk budget within all hard caps using a multiplier
    # derived from MEASURED edge (shadow avg_r + score-bucket avg_r), gated on
    # sufficient data. Direction follows the data — never "high score = good".
    # The multiplier is hard-clamped to [0.5, 1.5] inside RiskManager and can
    # never break any cap or the liquidation-safety invariant.
    risk_modulation_enabled: bool = field(
        default_factory=lambda: _bool("RISK_MODULATION_ENABLED", False)
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
    dashboard_port: int = field(default_factory=lambda: _pint("DASHBOARD_PORT"))
    # Heartbeat staleness cut for the ENGINE LOOP badge (ms). The heartbeat is
    # written at cycle END, so a slow scan cycle must not read as "engine down":
    # default = max(120s, 6 × cycle interval).
    heartbeat_stale_ms: int = field(default_factory=lambda: _int(
        "HEARTBEAT_STALE_MS",
        max(120_000, int(6 * _float("CYCLE_INTERVAL_SEC", 20.0) * 1000))))
    # Stale-data guard for NEW entries: if the freshest CLOSED signal-timeframe
    # bar is more than this many bar-lengths behind wall clock, the symbol is
    # skipped for new entries this cycle (reject reason "stale_data"). Open-trade
    # management is untouched. 0 disables. The synthetic provider is exempt
    # (deterministic offline timestamps).
    stale_entry_guard_bars: int = field(
        default_factory=lambda: _int("STALE_ENTRY_GUARD_BARS", 3))
    # Optional HTTP Basic auth (Task 4): when BOTH are set, every dashboard
    # route requires credentials EXCEPT /health (docker healthcheck hits it
    # from localhost). Unset (default) = behaviour unchanged.
    dashboard_auth_user: str = field(
        default_factory=lambda: _str("DASHBOARD_AUTH_USER", ""))
    dashboard_auth_pass: str = field(
        default_factory=lambda: _str("DASHBOARD_AUTH_PASS", ""))

    # -- Telegram (secrets via env only) -----------------------------------
    telegram_enabled: bool = field(default_factory=lambda: _bool("TELEGRAM_ENABLED", True))
    telegram_bot_token: str = field(default_factory=lambda: _str("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _str("TELEGRAM_CHAT_ID", ""))

    # -- Binance read-only account adapter (Live Stage 1) --------------------
    # Keys are OPTIONAL: absent → adapter reports "keys_absent" and the engine
    # behaves exactly as today. Present → GET-class account reads only (balance,
    # positions, open orders, exchangeInfo filters, leverage brackets, fees,
    # time drift, permission self-check). NEVER used to send orders.
    binance_api_key: str = field(default_factory=lambda: _str("BINANCE_API_KEY", ""))
    binance_api_secret: str = field(default_factory=lambda: _str("BINANCE_API_SECRET", ""))
    # Slow refresh timer (seconds) — runs OUTSIDE the trade cycle's critical path.
    binance_account_refresh_sec: float = field(
        default_factory=lambda: _float("BINANCE_ACCOUNT_REFRESH_SEC", 300.0))

    # -- Live safety gate --------------------------------------------------
    # LIVE_ENABLED must be explicitly true AND a human confirmation token set
    # for the live executor to even *attempt*. Real order sending (Stage 3)
    # additionally requires LIVE_SEND_ORDERS=true — the arming switch exists
    # so setups that relied on the pre-Stage-3 promise ("all three factors
    # set, orders still simulated") stay safe until this new, explicit opt-in.
    live_enabled: bool = field(default_factory=lambda: _bool("LIVE_ENABLED", False))
    live_human_confirm: str = field(default_factory=lambda: _str("LIVE_HUMAN_CONFIRM", ""))
    live_send_orders: bool = field(default_factory=lambda: _bool("LIVE_SEND_ORDERS", False))
    live_canary_risk_pct: float = field(default_factory=lambda: _float("LIVE_CANARY_RISK_PCT", 0.1))
    live_order_timeout_sec: float = field(default_factory=lambda: _float("LIVE_ORDER_TIMEOUT_SEC", 5.0))
    live_max_retries: int = field(default_factory=lambda: _int("LIVE_MAX_RETRIES", 2))

    # -- Governor (read-only reporting; NEVER a runtime layer) -------------
    # The Governor is a separate read-only command (`python main.py report`).
    # These flags document its report-only intent, but the REAL guarantee is
    # structural: it runs as its own process over a read-only DB connection and
    # imports nothing from the order path. It never trades, writes config, sets
    # any LIVE_*, or changes risk. Auto-apply of any recommendation is OFF.
    governor_mode: str = field(default_factory=lambda: _str("GOVERNOR_MODE", "report_only"))
    governor_can_trade: bool = field(
        default_factory=lambda: _bool("GOVERNOR_CAN_TRADE", False))
    governor_can_change_live: bool = field(
        default_factory=lambda: _bool("GOVERNOR_CAN_CHANGE_LIVE", False))
    governor_can_auto_apply: bool = field(
        default_factory=lambda: _bool("GOVERNOR_CAN_AUTO_APPLY", False))
    governor_requires_approval_for_risk_increase: bool = field(
        default_factory=lambda: _bool("GOVERNOR_REQUIRES_APPROVAL_FOR_RISK_INCREASE", True))
    # Setup-health / risk-throttle analyzers are REPORT-ONLY (Phase 6).
    risk_throttle_mode: str = field(
        default_factory=lambda: _str("RISK_THROTTLE_MODE", "report_only"))

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
        assert self.risk_profile in {"conservative_paper", "aggressive_paper"}, (
            "RISK_PROFILE must be conservative_paper|aggressive_paper"
        )
        assert self.min_risk_pct <= self.risk_pct <= self.max_risk_pct <= 5, (
            f"require min_risk_pct ({self.min_risk_pct}) <= risk_pct "
            f"({self.risk_pct}) <= max_risk_pct ({self.max_risk_pct}) <= 5"
        )
        assert self.mode in {"paper", "live"}, "AX_MODE must be 'paper' or 'live'"
        assert self.strategy_profile in {"bugra_replica", "aurvex_enhanced",
                                         "reversion_v1", "squeeze_breakout",
                                         "donchian_trend"}, (
            "STRATEGY_PROFILE must be bugra_replica|aurvex_enhanced|"
            "reversion_v1|squeeze_breakout|donchian_trend"
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
        # Governor guardrails: it is a read-only report, never an actor. These must
        # stay false — the Governor has no trade/live/auto-apply authority.
        assert not self.governor_can_trade, "GOVERNOR_CAN_TRADE must be false"
        assert not self.governor_can_change_live, "GOVERNOR_CAN_CHANGE_LIVE must be false"
        assert not self.governor_can_auto_apply, "GOVERNOR_CAN_AUTO_APPLY must be false"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


# Convenience singleton-style accessor (callers may also instantiate their own).
def load_config() -> Config:
    cfg = Config()
    cfg.validate()
    return cfg
