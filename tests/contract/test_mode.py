"""契约测试：模式开关默认值与合规约束（对应 tasks.md T015）。"""

from __future__ import annotations

import pytest

from gss_contracts import (
    AccountSource,
    BillingMode,
    CardSource,
    Mode,
    ModeValidationError,
    Plan,
)


def test_defaults_are_safe() -> None:
    """默认必须是 standard + customer + customer_session（宪法第 IV 条）。"""

    mode = Mode()
    assert mode.account_source is AccountSource.CUSTOMER_SESSION
    assert mode.card_source is CardSource.CUSTOMER
    assert mode.billing_mode is BillingMode.STANDARD
    assert mode.risk_acknowledged is False
    assert mode.is_high_risk is False
    mode.validate()  # 默认组合必须直接通过


def test_promo_requires_risk_acknowledgement() -> None:
    """promo 未确认风险必须被拒绝。"""

    with pytest.raises(ModeValidationError) as exc:
        Mode(billing_mode=BillingMode.PROMO).validate()
    assert exc.value.code == "promo_not_acknowledged"


def test_promo_with_acknowledgement_passes() -> None:
    """promo 显式确认后允许通过，且被标记为高风险。"""

    mode = Mode(billing_mode=BillingMode.PROMO, risk_acknowledged=True)
    mode.validate()
    assert mode.is_high_risk is True


def test_unsupported_promo_combination_is_blocked() -> None:
    """客户账号 + 平台卡 + 促销 组合必须被拒绝。"""

    mode = Mode(
        account_source=AccountSource.CUSTOMER_SESSION,
        card_source=CardSource.PLATFORM,
        billing_mode=BillingMode.PROMO,
        risk_acknowledged=True,
    )
    with pytest.raises(ModeValidationError) as exc:
        mode.validate()
    assert exc.value.code == "promo_platform_card_on_customer_account"


def test_platform_account_standard_is_allowed() -> None:
    """平台账号 + 平台卡 + 正价（开通后交付账号）允许。"""

    Mode(
        account_source=AccountSource.PLATFORM_ACCOUNT,
        card_source=CardSource.PLATFORM,
        billing_mode=BillingMode.STANDARD,
    ).validate()


def test_mode_is_frozen_and_hashable() -> None:
    """Mode 必须不可变，可作为幂等键的一部分。"""

    mode = Mode()
    assert hash(mode) == hash(Mode())
    with pytest.raises(Exception):
        mode.billing_mode = BillingMode.PROMO  # type: ignore[misc]


def test_plan_enum_covers_all_tiers() -> None:
    assert {p.value for p in Plan} == {"plus", "go", "pro_lite", "pro", "pro_max", "team"}
