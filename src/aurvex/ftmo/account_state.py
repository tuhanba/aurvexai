"""FtmoAccountState — the live FTMO rule budgets for one account.

This is the heart of FTMO Mode. Each cycle the engine feeds it the SAME money
numbers the accounting reconciler already produces (``balance`` = realized cash,
``equity`` = cash + open mark-to-market) plus the current wall-clock. From those
it maintains, in FTMO's exact terms:

  * ``day_open_balance`` — balance snapshot at the last 00:00 CE(S)T reset.
  * ``high_water_balance`` — ratcheting peak REALIZED balance (never decreases);
    the trailing max-loss floor rides on this.
  * ``remaining_daily_loss`` / ``remaining_max_loss`` — headroom to each rule,
    measured on EQUITY (floating PnL counts, exactly like FTMO).
  * ``daily_risk_budget`` — how much loss may still be risked today.
  * breach flags and profit-target progress.

Design notes:
  * Monitoring is on EQUITY (floating counts) — the strict reading FTMO enforces.
  * The high-water ratchet uses REALIZED balance (FTMO trails the highest
    achieved balance, not floating equity). This is the conservative choice.
  * The daily reset is CE(S)T-based via ``ftmo_calendar`` (DST-correct).
  * Pure state object: no I/O. ``to_dict``/``from_dict`` let the engine persist
    the CE(S)T baseline + high-water across restarts (via ``meta``), which is
    essential — losing the day-open baseline would silently reset the budget.

Wave 0 wires nothing into the engine; this object is exercised by tests only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import ftmo_calendar as cal
from .rules import CHALLENGE, VERIFICATION, FtmoRuleSet


@dataclass
class FtmoAccountState:
    ruleset: FtmoRuleSet
    day_open_balance: float
    high_water_balance: float
    balance: float = 0.0
    equity: float = 0.0
    floating_pnl: float = 0.0
    day_ordinal: int = 0
    # CE(S)T calendar-day ordinals on which at least one position was opened.
    traded_ordinals: List[int] = field(default_factory=list)
    # Fraction of the remaining rule budget that may be risked in a single day.
    # 1.0 = the full headroom; the mode/health layer (later wave) tightens this.
    daily_budget_fraction: float = 1.0

    # -- constructors --------------------------------------------------------
    @classmethod
    def initial(cls, ruleset: FtmoRuleSet,
                starting_balance: Optional[float] = None,
                now_ms: Optional[int] = None) -> "FtmoAccountState":
        bal = ruleset.account_size if starting_balance is None else float(starting_balance)
        ordn = cal.day_ordinal(now_ms, ruleset.tz) if now_ms is not None else 0
        return cls(
            ruleset=ruleset,
            day_open_balance=bal,
            high_water_balance=max(bal, ruleset.account_size),
            balance=bal,
            equity=bal,
            floating_pnl=0.0,
            day_ordinal=ordn,
        )

    # -- per-cycle update ----------------------------------------------------
    def roll_day_if_needed(self, now_ms: int) -> bool:
        """Apply the CE(S)T daily reset if ``now_ms`` is a new local day.

        On rollover the daily baseline becomes the current REALIZED balance and
        the high-water ratchet is refreshed. Returns True if a reset happened.
        """
        ordn = cal.day_ordinal(now_ms, self.ruleset.tz)
        if self.day_ordinal == 0:
            self.day_ordinal = ordn
            return False
        if ordn > self.day_ordinal:
            self.day_open_balance = self.balance
            if self.balance > self.high_water_balance:
                self.high_water_balance = self.balance
            self.day_ordinal = ordn
            return True
        return False

    def update(self, balance: float, equity: float, now_ms: int) -> None:
        """Refresh state from the latest money numbers + wall-clock.

        ``balance`` is realized cash; ``equity`` is cash + open mark-to-market.
        Call once per cycle after reconciliation.
        """
        self.roll_day_if_needed(now_ms)
        self.balance = float(balance)
        self.equity = float(equity)
        self.floating_pnl = self.equity - self.balance
        # High-water ratchets on realized balance only (never on floating equity).
        if self.balance > self.high_water_balance:
            self.high_water_balance = self.balance

    def record_trade(self, now_ms: int) -> None:
        """Mark that a position was opened on this CE(S)T day (for min-days)."""
        ordn = cal.day_ordinal(now_ms, self.ruleset.tz)
        if ordn not in self.traded_ordinals:
            self.traded_ordinals.append(ordn)

    # -- rule floors ---------------------------------------------------------
    @property
    def daily_loss_floor(self) -> float:
        return self.ruleset.daily_loss_floor(self.day_open_balance)

    @property
    def max_loss_floor(self) -> float:
        return self.ruleset.max_loss_floor(self.high_water_balance)

    # -- headroom (measured on EQUITY) --------------------------------------
    @property
    def remaining_daily_loss(self) -> float:
        """Equity we can still lose today before the daily rule breaches (>=0)."""
        return max(0.0, self.equity - self.daily_loss_floor)

    @property
    def remaining_max_loss(self) -> float:
        """Equity we can still lose before the overall rule breaches (>=0)."""
        return max(0.0, self.equity - self.max_loss_floor)

    @property
    def current_drawdown(self) -> float:
        """Equity distance below the ratcheting high-water balance (>=0)."""
        return max(0.0, self.high_water_balance - self.equity)

    @property
    def daily_risk_budget(self) -> float:
        """Loss that may still be risked today: the tighter of the two rule
        headrooms, scaled by ``daily_budget_fraction``."""
        binding = min(self.remaining_daily_loss, self.remaining_max_loss)
        return max(0.0, binding * self.daily_budget_fraction)

    # -- breach flags (equity basis) ----------------------------------------
    @property
    def daily_breached(self) -> bool:
        return self.equity <= self.daily_loss_floor

    @property
    def max_loss_breached(self) -> bool:
        return self.equity <= self.max_loss_floor

    @property
    def any_breach(self) -> bool:
        return self.daily_breached or self.max_loss_breached

    # -- progress ------------------------------------------------------------
    @property
    def profit_since_start(self) -> float:
        return self.equity - self.ruleset.account_size

    @property
    def profit_target_reached(self) -> bool:
        if not self.ruleset.has_profit_target:
            return False
        return self.profit_since_start >= self.ruleset.profit_target_amount()

    @property
    def phase_progress_pct(self) -> float:
        """Percent of the phase profit target reached (0..100+, 0 if no target)."""
        target = self.ruleset.profit_target_amount()
        if target <= 0:
            return 0.0
        return round(self.profit_since_start / target * 100.0, 2)

    @property
    def trading_days_done(self) -> int:
        return len(self.traded_ordinals)

    @property
    def trading_days_remaining(self) -> int:
        return max(0, self.ruleset.min_trading_days - self.trading_days_done)

    # -- serialization (for meta persistence across restarts) ----------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ruleset": self.ruleset.__dict__,
            "day_open_balance": self.day_open_balance,
            "high_water_balance": self.high_water_balance,
            "balance": self.balance,
            "equity": self.equity,
            "floating_pnl": self.floating_pnl,
            "day_ordinal": self.day_ordinal,
            "traded_ordinals": list(self.traded_ordinals),
            "daily_budget_fraction": self.daily_budget_fraction,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FtmoAccountState":
        rs = FtmoRuleSet(**d["ruleset"])
        return cls(
            ruleset=rs,
            day_open_balance=float(d["day_open_balance"]),
            high_water_balance=float(d["high_water_balance"]),
            balance=float(d.get("balance", 0.0)),
            equity=float(d.get("equity", 0.0)),
            floating_pnl=float(d.get("floating_pnl", 0.0)),
            day_ordinal=int(d.get("day_ordinal", 0)),
            traded_ordinals=list(d.get("traded_ordinals", [])),
            daily_budget_fraction=float(d.get("daily_budget_fraction", 1.0)),
        )

    def summary(self) -> Dict[str, Any]:
        """Flat, dashboard/telegram-friendly view of the current budgets."""
        rs = self.ruleset
        return {
            "path": rs.path,
            "phase": rs.phase,
            "account_size": rs.account_size,
            "variant": rs.account_variant,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "floating_pnl": round(self.floating_pnl, 2),
            "day_open_balance": round(self.day_open_balance, 2),
            "high_water_balance": round(self.high_water_balance, 2),
            "remaining_daily_loss": round(self.remaining_daily_loss, 2),
            "remaining_max_loss": round(self.remaining_max_loss, 2),
            "current_drawdown": round(self.current_drawdown, 2),
            "daily_risk_budget": round(self.daily_risk_budget, 2),
            "daily_loss_floor": round(self.daily_loss_floor, 2),
            "max_loss_floor": round(self.max_loss_floor, 2),
            "daily_breached": self.daily_breached,
            "max_loss_breached": self.max_loss_breached,
            "profit_since_start": round(self.profit_since_start, 2),
            "phase_progress_pct": self.phase_progress_pct,
            "profit_target_reached": self.profit_target_reached,
            "trading_days_done": self.trading_days_done,
            "trading_days_remaining": self.trading_days_remaining,
        }
