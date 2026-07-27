"""FTMO Mode — a rule-governance and account-management layer.

Phase 1 (this package) is EXECUTION-VENUE-AGNOSTIC and OBSERVE-ONLY by default.
It encodes FTMO's exact rule math (daily loss, overall max loss, targets,
trading-day + weekend rules) as data + pure functions, so the existing shared
decision brain can later be gated on FTMO compliance without ever forking it.

Non-negotiables honoured (see CLAUDE.md):
  * No real orders. Nothing here touches an exchange or the Binance five-gate
    lock. FTMO execution (an MT5/FTMO adapter) is a separate, later wave.
  * Paper/live parity. FTMO state is fed money numbers (balance, equity,
    high-water) that are identical across paper/live/backtest, so any future
    gate built on it stays parity-safe.
  * Rule-compliance only — never an alpha/ML veto.

Wave 0 ships the read-only primitives only:
  * ``rules``          — FtmoRuleSet (the numbers, as data)
  * ``ftmo_calendar``  — CE(S)T (Europe/Prague) day boundary + weekend helpers
  * ``account_state``  — FtmoAccountState: budgets, high-water, breach flags
"""
from __future__ import annotations

from .account_state import FtmoAccountState
from .rules import (CHALLENGE, FUNDED, ONE_STEP, STANDARD, STATIC, SWING,
                    TRAILING, TWO_STEP, VERIFICATION, FtmoRuleSet,
                    ruleset_for)

__all__ = [
    "FtmoRuleSet",
    "ruleset_for",
    "FtmoAccountState",
    "ONE_STEP",
    "TWO_STEP",
    "CHALLENGE",
    "VERIFICATION",
    "FUNDED",
    "STATIC",
    "TRAILING",
    "STANDARD",
    "SWING",
]
