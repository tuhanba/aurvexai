"""FTMO rule-set math (Wave 0)."""
from aurvex.ftmo.rules import (CHALLENGE, FUNDED, ONE_STEP, STANDARD, STATIC,
                               SWING, TRAILING, TWO_STEP, VERIFICATION,
                               FtmoRuleSet, ruleset_for)


def test_two_step_challenge_defaults():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000)
    assert rs.profit_target_pct == 10.0
    assert rs.daily_loss_pct == 5.0
    assert rs.max_loss_pct == 10.0
    assert rs.max_loss_mode == STATIC
    assert rs.min_trading_days == 4
    assert rs.weekend_flat_required is True
    assert rs.has_profit_target is True


def test_two_step_verification_target_is_5():
    rs = ruleset_for(TWO_STEP, VERIFICATION, account_size=100_000)
    assert rs.profit_target_pct == 5.0
    assert rs.min_trading_days == 4


def test_funded_has_no_profit_target():
    rs = ruleset_for(TWO_STEP, FUNDED, account_size=100_000)
    assert rs.profit_target_pct == 0.0
    assert rs.has_profit_target is False
    assert rs.min_trading_days == 0


def test_one_step_uses_3pct_daily_and_trailing():
    rs = ruleset_for(ONE_STEP, CHALLENGE, account_size=100_000)
    assert rs.daily_loss_pct == 3.0
    assert rs.max_loss_mode == TRAILING
    assert rs.min_trading_days == 0
    assert rs.consistency_max_day_pct == 50.0
    assert rs.profit_split_pct == 90.0


def test_amounts_scale_with_account_size():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=200_000)
    assert rs.daily_loss_amount() == 10_000.0     # 5%
    assert rs.max_loss_amount() == 20_000.0        # 10%
    assert rs.profit_target_amount() == 20_000.0   # 10%


def test_daily_loss_floor_uses_day_open_balance():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000)
    # day opened up at 103k -> floor tracks the day-open, not the initial size
    assert rs.daily_loss_floor(103_000) == 103_000 - 5_000


def test_static_max_loss_floor_is_fixed():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000)
    # High-water is irrelevant for the static rule.
    assert rs.max_loss_floor(100_000) == 90_000
    assert rs.max_loss_floor(130_000) == 90_000


def test_trailing_max_loss_floor_ratchets_but_floors_at_initial():
    rs = ruleset_for(ONE_STEP, CHALLENGE, account_size=100_000)
    # Before any profit, the trailing floor cannot sit below the static level.
    assert rs.max_loss_floor(95_000) == 90_000
    assert rs.max_loss_floor(100_000) == 90_000
    # Once balance ratchets up, the floor follows 10% below the high-water.
    assert rs.max_loss_floor(108_000) == 98_000


def test_swing_variant_removes_weekend_and_news():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000, variant=SWING)
    assert rs.is_swing is True
    assert rs.weekend_flat_required is False
    assert rs.news_buffer_minutes == 0.0


def test_standard_variant_keeps_weekend_and_news():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000, variant=STANDARD)
    assert rs.weekend_flat_required is True
    assert rs.news_buffer_minutes == 2.0


def test_with_overrides_returns_copy():
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=100_000)
    rs2 = rs.with_overrides(tz="Europe/Berlin")
    assert rs.tz == "Europe/Prague"
    assert rs2.tz == "Europe/Berlin"
    assert isinstance(rs2, FtmoRuleSet)
