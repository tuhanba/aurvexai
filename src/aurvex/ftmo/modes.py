"""FTMO operating-mode state machine.

The account's *situation* selects a behavioural mode; each mode is a small
``ModeProfile`` of risk-shaping inputs. Modes never touch ``decide()``'s
allow/reject logic — they only change the *inputs* the shared brain reads (risk
fraction, slot cap, confidence bump, daily-budget fraction, allow-new-risk),
exactly like a config profile. Parity is therefore preserved.

    CHALLENGE  — pass the evaluation with margin (balanced).
    FUNDED     — protect the funded account (protect-first, no-trade bias).
    PAYOUT     — safely reach the payout date (minimal, high-conviction only).
    RECOVERY   — climb out of a drawdown slowly (halved risk, higher bar).
    SURVIVAL   — never lose the account (freeze new risk; manage/flatten only).

``next_mode`` is a pure function of the account state + rule set (+ an optional
payout-window flag the engine supplies from the payout calendar). Thresholds are
parameters with conservative defaults so they can be tuned/validated later.
"""
from __future__ import annotations

from dataclasses import dataclass

from .account_state import FtmoAccountState
from .rules import FUNDED

# -- modes -------------------------------------------------------------------
CHALLENGE = "challenge"
FUNDED_MODE = "funded"
PAYOUT = "payout"
RECOVERY = "recovery"
SURVIVAL = "survival"

# -- default transition thresholds (fractions of the respective rule amount) --
# Enter SURVIVAL when the tighter of the two loss headrooms falls to/under this
# fraction of its rule amount (e.g. 15% of the daily/overall budget left).
DEFAULT_SURVIVAL_FRAC = 0.15
# Enter RECOVERY when current drawdown reaches this fraction of the max-loss.
DEFAULT_RECOVERY_DD_FRAC = 0.5


@dataclass(frozen=True)
class ModeProfile:
    """Risk-shaping inputs for a mode. All are *modulators* of existing config.

    risk_fraction        : multiply the configured risk_pct by this (<=1 = safer).
    daily_budget_fraction: fraction of the FTMO daily budget usable in one day.
    max_open_cap         : hard cap on concurrent trades (min with config).
    confidence_bump      : add to the effective confidence/score threshold.
    allow_new_risk       : if False, no new positions may be opened at all.
    """
    name: str
    risk_fraction: float
    daily_budget_fraction: float
    max_open_cap: int
    confidence_bump: float
    allow_new_risk: bool


_PROFILES = {
    CHALLENGE: ModeProfile(CHALLENGE, 1.0, 0.5, 99, 0.0, True),
    FUNDED_MODE: ModeProfile(FUNDED_MODE, 0.6, 0.3, 3, 5.0, True),
    PAYOUT: ModeProfile(PAYOUT, 0.3, 0.15, 1, 10.0, True),
    RECOVERY: ModeProfile(RECOVERY, 0.5, 0.25, 2, 8.0, True),
    SURVIVAL: ModeProfile(SURVIVAL, 0.0, 0.0, 0, 100.0, False),
}


def mode_profile(mode: str) -> ModeProfile:
    """The ModeProfile for a mode name (defaults to CHALLENGE if unknown)."""
    return _PROFILES.get(mode, _PROFILES[CHALLENGE])


def next_mode(state: FtmoAccountState, *, payout_window: bool = False,
              survival_frac: float = DEFAULT_SURVIVAL_FRAC,
              recovery_dd_frac: float = DEFAULT_RECOVERY_DD_FRAC) -> str:
    """Select the operating mode for the current account situation.

    Priority (most protective first): SURVIVAL → RECOVERY → PAYOUT → FUNDED →
    CHALLENGE. ``payout_window`` is supplied by the engine when a funded account
    is close to its payout date.
    """
    rs = state.ruleset
    daily_amt = rs.daily_loss_amount() or 1.0
    max_amt = rs.max_loss_amount() or 1.0

    # SURVIVAL: either budget nearly exhausted, or already breached.
    daily_headroom_frac = state.remaining_daily_loss / daily_amt
    max_headroom_frac = state.remaining_max_loss / max_amt
    if state.any_breach or min(daily_headroom_frac, max_headroom_frac) <= survival_frac:
        return SURVIVAL

    # RECOVERY: meaningful drawdown below the high-water.
    if state.current_drawdown >= recovery_dd_frac * max_amt:
        return RECOVERY

    # Funded account: PAYOUT near the payout date, else FUNDED.
    if rs.phase == FUNDED:
        return PAYOUT if payout_window else FUNDED_MODE

    # Challenge / Verification.
    return CHALLENGE
