"""契约测试：订单 / 支付状态机（对应 tasks.md T006、T023）。"""

from __future__ import annotations

import pytest

from dcp_contracts import (
    ORDER_TRANSITIONS,
    PAYMENT_TRANSITIONS,
    DELIVERABLE_ORDER_STATUSES,
    IllegalTransition,
    OrderStatus,
    PaymentStatus,
    assert_transition,
    can_transition,
    is_deliverable,
    is_terminal,
)


def test_legal_happy_path_transitions() -> None:
    """正价链路：created → … → delivered 全程合法。"""

    path = [
        OrderStatus.CREATED,
        OrderStatus.PENDING_CHECKOUT,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.PAYING,
        OrderStatus.VERIFYING,
        OrderStatus.ACTIVE,
        OrderStatus.DELIVERED,
    ]
    for current, target in zip(path, path[1:]):
        assert_transition(current, target)


def test_requires_action_round_trip() -> None:
    """3DS：paying → requires_action → paying 合法。"""

    assert_transition(OrderStatus.PAYING, OrderStatus.REQUIRES_ACTION)
    assert_transition(OrderStatus.REQUIRES_ACTION, OrderStatus.PAYING)


def test_unknown_is_retryable_not_terminal() -> None:
    """不确定终态可回到 paying 重试，且不是终态。"""

    assert_transition(OrderStatus.PAYING, OrderStatus.UNKNOWN)
    assert_transition(OrderStatus.UNKNOWN, OrderStatus.PAYING)
    assert not is_terminal(OrderStatus.UNKNOWN)


def test_cannot_skip_verification_and_deliver() -> None:
    """不允许从 paying 直接跳到 delivered（必须经 verifying 确认订阅生效）。"""

    with pytest.raises(IllegalTransition):
        assert_transition(OrderStatus.PAYING, OrderStatus.DELIVERED)
    assert not can_transition(OrderStatus.PAYING, OrderStatus.DELIVERED)


def test_cannot_deliver_without_active() -> None:
    """只有 active 可交付，verifying 不可。"""

    assert is_deliverable(OrderStatus.ACTIVE)
    assert not is_deliverable(OrderStatus.VERIFYING)
    assert DELIVERABLE_ORDER_STATUSES == frozenset({OrderStatus.ACTIVE})


def test_terminal_statuses_have_no_outgoing_edges() -> None:
    """终态的定义是「没有任何出边」，不得再迁移。"""

    for status in [
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.REFUNDED,
    ]:
        assert is_terminal(status)
        assert ORDER_TRANSITIONS[status] == frozenset()


def test_delivered_is_not_terminal_because_refund_is_allowed() -> None:
    """交付后仍可能退款，所以 delivered 不是终态，但可迁移到 refunded。"""

    assert not is_terminal(OrderStatus.DELIVERED)
    assert_transition(OrderStatus.DELIVERED, OrderStatus.REFUNDED)


def test_payment_transitions_cover_3ds() -> None:
    """支付状态机同样支持 3DS。"""

    assert (
        PaymentStatus.REQUIRES_ACTION
        in PAYMENT_TRANSITIONS[PaymentStatus.PROCESSING]
    )
    assert PaymentStatus.SUCCEEDED in PAYMENT_TRANSITIONS[PaymentStatus.PROCESSING]
    assert PAYMENT_TRANSITIONS[PaymentStatus.SUCCEEDED] == frozenset()


def test_every_status_is_reachable_and_declared() -> None:
    """迁移表必须覆盖所有订单状态（无遗漏）。"""

    assert set(ORDER_TRANSITIONS) == set(OrderStatus)
