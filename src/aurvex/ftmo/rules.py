"""FTMO rule set — the numbers, as DATA (never hard-coded literals elsewhere).

Every FTMO limit lives in an :class:`FtmoRuleSet` instance so the engine reads
fields, not constants. FTMO tweaks these periodically (the 1-Step launched
Feb 2026; the old 30-day time limit was removed), so ``rules_source_date`` is
carried alongside and must be re-verified against ftmo.com before any funded use.

Sources (verified 2026-07-27):
  * https://ftmo.com/en/trading-objectives/
  * https://ftmo.com/en/how-it-works/

The default numbers below are the standard published values:

  ============ ============= ============ ============ ============= ==========
  path/phase   profit target daily loss   max loss     max-loss mode min days
  ============ ============= ============ ============ ============= ==========
  2-step P1    10%           5%           10%          static        4
  2-step P2    5%            5%           10%          static        4
  2-step fund. (none)        5%           10%          static        0
  1-step P1    10%           3%           10%          trailing      0
  1-step fund. (none)        3%           10%          trailing      0
  ============ ============= ============ ============ ============= ==========

All amounts are a percentage of the INITIAL account size (``account_size``).
The daily-loss reference is the balance at 00:00 CE(S)T of the current day; the
overall max-loss reference is the initial balance (static) or the ratcheting
high-water balance (trailing). Both rules are monitored on EQUITY (floating PnL
counts), which is why they are stricter than a realized-only kill switch.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# -- path --------------------------------------------------------------------
ONE_STEP = "one_step"
TWO_STEP = "two_step"

# -- phase -------------------------------------------------------------------
CHALLENGE = "challenge"
VERIFICATION = "verification"
FUNDED = "funded"

# -- overall max-loss mode ---------------------------------------------------
STATIC = "static"
TRAILING = "trailing"

# -- account variant ---------------------------------------------------------
STANDARD = "standard"
SWING = "swing"

# CE(S)T. Europe/Prague observes Central European (Summer) Time, matching FTMO's
# published reset timezone including DST.
FTMO_TZ = "Europe/Prague"


@dataclass(frozen=True)
class FtmoRuleSet:
    """Immutable FTMO rule parameters for a single configured account."""

    account_size: float = 100_000.0
    path: str = TWO_STEP            # one_step | two_step
    phase: str = CHALLENGE          # challenge | verification | funded
    profit_target_pct: float = 10.0
    daily_loss_pct: float = 5.0
    max_loss_pct: float = 10.0
    max_loss_mode: str = STATIC     # static | trailing
    min_trading_days: int = 4
    account_variant: str = STANDARD  # standard | swing
    weekend_flat_required: bool = True
    news_buffer_minutes: float = 2.0
    # Consistency / best-day rule: single best day <= this % of total positive
    # profit at payout. 0 = disabled. (FTMO applies ~50% on the 1-Step path.)
    consistency_max_day_pct: float = 0.0
    profit_split_pct: float = 80.0
    tz: str = FTMO_TZ
    rules_source_date: str = "2026-07-27"

    # -- absolute amounts (currency of the account) --------------------------
    def daily_loss_amount(self) -> float:
        return self.account_size * self.daily_loss_pct / 100.0

    def max_loss_amount(self) -> float:
        return self.account_size * self.max_loss_pct / 100.0

    def profit_target_amount(self) -> float:
        return self.account_size * self.profit_target_pct / 100.0

    # -- rule floors ---------------------------------------------------------
    def daily_loss_floor(self, day_open_balance: float) -> float:
        """Equity level at/under which the DAILY loss rule is breached today.

        ``day_open_balance`` is the balance recorded at 00:00 CE(S)T today.
        """
        return day_open_balance - self.daily_loss_amount()

    def max_loss_floor(self, high_water_balance: float) -> float:
        """Equity level at/under which the OVERALL max-loss rule is breached.

        static   : ``initial - max_loss_amount`` (fixed for the account's life).
        trailing : ``high_water - max_loss_amount`` where ``high_water`` ratchets
                   up with realized balance and never decreases; floored at the
                   initial size so it can never sit below the static level early.
        """
        if self.max_loss_mode == TRAILING:
            base = max(high_water_balance, self.account_size)
        else:
            base = self.account_size
        return base - self.max_loss_amount()

    # -- variant helpers -----------------------------------------------------
    @property
    def is_swing(self) -> bool:
        return self.account_variant == SWING

    @property
    def has_profit_target(self) -> bool:
        return self.phase in (CHALLENGE, VERIFICATION) and self.profit_target_pct > 0

    def with_overrides(self, **kwargs) -> "FtmoRuleSet":
        """Return a copy with the given fields replaced (frozen dataclass)."""
        return replace(self, **kwargs)


# --------------------------------------------------------------------------
# Standard published presets. Callers pass an account_size (and optional
# variant) and get the correct numbers for the path/phase. Any single number
# can still be overridden via ``with_overrides`` / config.
# --------------------------------------------------------------------------
def ruleset_for(path: str = TWO_STEP, phase: str = CHALLENGE,
                account_size: float = 100_000.0,
                variant: str = STANDARD) -> FtmoRuleSet:
    """Build the standard FtmoRuleSet for a path/phase.

    Swing forces weekend-hold + news exemptions off; Standard keeps them on.
    """
    path = (path or TWO_STEP).lower()
    phase = (phase or CHALLENGE).lower()
    variant = (variant or STANDARD).lower()

    if path == ONE_STEP:
        daily_loss_pct = 3.0
        max_loss_mode = TRAILING
        min_days = 0
        consistency = 50.0
        split = 90.0
    else:
        daily_loss_pct = 5.0
        max_loss_mode = STATIC
        min_days = 4
        consistency = 0.0
        split = 80.0

    if phase == VERIFICATION:
        target = 5.0
    elif phase == FUNDED:
        target = 0.0
        min_days = 0
    else:  # challenge
        target = 10.0

    # Swing is only offered on the 2-Step path; if requested elsewhere we still
    # honour the exemptions but the caller is responsible for eligibility.
    swing = variant == SWING
    return FtmoRuleSet(
        account_size=float(account_size),
        path=path,
        phase=phase,
        profit_target_pct=target,
        daily_loss_pct=daily_loss_pct,
        max_loss_pct=10.0,
        max_loss_mode=max_loss_mode,
        min_trading_days=min_days,
        account_variant=variant,
        weekend_flat_required=not swing,
        news_buffer_minutes=0.0 if swing else 2.0,
        consistency_max_day_pct=consistency,
        profit_split_pct=split,
    )
