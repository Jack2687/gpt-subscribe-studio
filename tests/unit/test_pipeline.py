"""编排流水线测试：阶段编排、支付→订单映射、交付门槛（tasks.md T020/T027/T032）。"""

from __future__ import annotations

import asyncio

import pytest

from dcp_account import FakeAccountAdapter
from dcp_checkout import FakeCheckoutAdapter
from dcp_contracts import (
    BillingMode,
    CardSource,
    Mode,
    OrderStatus,
    PaymentStatus,
    Plan,
    SubscriptionInfo,
)
from dcp_contracts.errors import DomainError
from dcp_orchestrator.pipeline import (
    OrderPipeline,
    PipelineDeps,
    assert_deliverable,
    next_order_status,
)
from dcp_payment import FakePaymentAdapter


def build_deps(payment_script=None, active=True) -> PipelineDeps:
    return PipelineDeps(
        checkout=FakeCheckoutAdapter(),
        payment=FakePaymentAdapter(scripted=payment_script or [PaymentStatus.SUCCEEDED]),
        account=FakeAccountAdapter(active=active),
    )


def test_happy_path_checkout_pay_verify() -> None:
    pipeline = OrderPipeline(build_deps())
    checkout = asyncio.run(
        pipeline.create_checkout(
            session="s", plan=Plan.PLUS, billing_country="US", mode=Mode()
        )
    )
    assert checkout.currency == "USD"

    payment = asyncio.run(
        pipeline.pay(
            checkout_url=checkout.checkout_url,
            country="US",
            mode=Mode(),
            payment_method_token="pm_fake",
        )
    )
    assert payment.status is PaymentStatus.SUCCEEDED

    info = asyncio.run(pipeline.verify(session="s"))
    assert info.active is True


def test_platform_card_requires_card_id() -> None:
    pipeline = OrderPipeline(build_deps())
    with pytest.raises(DomainError):
        asyncio.run(
            pipeline.pay(
                checkout_url="u", country="US", mode=Mode(card_source=CardSource.PLATFORM)
            )
        )


def test_customer_card_requires_payment_method_token() -> None:
    pipeline = OrderPipeline(build_deps())
    with pytest.raises(DomainError):
        asyncio.run(pipeline.pay(checkout_url="u", country="US", mode=Mode()))


def test_promo_without_acknowledgement_blocked_before_checkout() -> None:
    pipeline = OrderPipeline(build_deps())
    with pytest.raises(Exception) as exc:
        asyncio.run(
            pipeline.create_checkout(
                session="s",
                plan=Plan.PLUS,
                billing_country="US",
                mode=Mode(billing_mode=BillingMode.PROMO),
            )
        )
    assert "promo" in str(exc.value)


def test_next_order_status_mapping() -> None:
    from dcp_orchestrator.pipeline import apply_payment_result

    assert next_order_status(OrderStatus.PAYING, PaymentStatus.SUCCEEDED) is OrderStatus.VERIFYING
    assert apply_payment_result(OrderStatus.AWAITING_PAYMENT, PaymentStatus.SUCCEEDED) is OrderStatus.VERIFYING
    assert (
        next_order_status(OrderStatus.PAYING, PaymentStatus.REQUIRES_ACTION)
        is OrderStatus.REQUIRES_ACTION
    )
    assert next_order_status(OrderStatus.PAYING, PaymentStatus.ERROR) is OrderStatus.UNKNOWN
    assert next_order_status(OrderStatus.PAYING, PaymentStatus.DECLINED) is OrderStatus.FAILED


def test_next_order_status_rejects_illegal_transition() -> None:
    """已交付订单不能再回到 paying。"""

    with pytest.raises(Exception):
        next_order_status(OrderStatus.DELIVERED, PaymentStatus.PROCESSING)


def test_delivery_gate_blocks_inactive_subscription() -> None:
    with pytest.raises(DomainError):
        assert_deliverable(OrderStatus.ACTIVE, SubscriptionInfo(active=False))


def test_delivery_gate_blocks_non_active_order_status() -> None:
    with pytest.raises(DomainError):
        assert_deliverable(OrderStatus.VERIFYING, SubscriptionInfo(active=True))


def test_delivery_gate_allows_active_and_verified() -> None:
    assert_deliverable(OrderStatus.ACTIVE, SubscriptionInfo(active=True))
