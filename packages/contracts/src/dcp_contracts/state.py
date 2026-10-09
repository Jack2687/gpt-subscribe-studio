"""显式状态机：订单与支付的状态及其合法迁移。

见 ADR 0002。禁止用布尔值表达「成功 / 失败」——上游存在大量不确定终态，
必须区分「请求成功」「待确认」「3DS next-action」「订阅最终生效」。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # Python 3.9 / 3.10 兼容
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """`str` 枚举回退实现（Python < 3.11）。"""

        def __str__(self) -> str:
            return str(self.value)


class OrderStatus(StrEnum):
    """订单状态。"""

    CREATED = "created"
    PENDING_CHECKOUT = "pending_checkout"
    AWAITING_PAYMENT = "awaiting_payment"
    PAYING = "paying"
    REQUIRES_ACTION = "requires_action"
    UNKNOWN = "unknown"
    VERIFYING = "verifying"
    ACTIVE = "active"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    """单次支付尝试的状态。"""

    INITIATED = "initiated"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    REQUIRES_ACTION = "requires_action"
    DECLINED = "declined"
    ERROR = "error"


#: 不会再有任何出边迁移的订单状态。
#: 注意 ``DELIVERED`` **不在此集合**：交付后仍可能 ``refunded``，
#: 见 ``ORDER_TRANSITIONS``。终态的定义是「没有任何出边」。
TERMINAL_ORDER_STATUSES: FrozenSet[OrderStatus] = frozenset(
    {
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.REFUNDED,
    }
)

#: 订阅已确认生效、允许交付的状态。
DELIVERABLE_ORDER_STATUSES: FrozenSet[OrderStatus] = frozenset({OrderStatus.ACTIVE})

#: 需要人工或重试介入、但尚未失败的状态。
PENDING_ORDER_STATUSES: FrozenSet[OrderStatus] = frozenset(
    {
        OrderStatus.CREATED,
        OrderStatus.PENDING_CHECKOUT,
        OrderStatus.AWAITING_PAYMENT,
        OrderStatus.PAYING,
        OrderStatus.REQUIRES_ACTION,
        OrderStatus.UNKNOWN,
        OrderStatus.VERIFYING,
    }
)


#: 合法订单迁移表（`from` → 允许的 `to`）。
ORDER_TRANSITIONS: Dict[OrderStatus, FrozenSet[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.PENDING_CHECKOUT, OrderStatus.REJECTED, OrderStatus.FAILED}
    ),
    OrderStatus.PENDING_CHECKOUT: frozenset(
        {OrderStatus.AWAITING_PAYMENT, OrderStatus.FAILED}
    ),
    OrderStatus.AWAITING_PAYMENT: frozenset({OrderStatus.PAYING, OrderStatus.FAILED}),
    OrderStatus.PAYING: frozenset(
        {
            OrderStatus.VERIFYING,
            OrderStatus.REQUIRES_ACTION,
            OrderStatus.UNKNOWN,
            OrderStatus.FAILED,
        }
    ),
    OrderStatus.REQUIRES_ACTION: frozenset({OrderStatus.PAYING, OrderStatus.FAILED}),
    OrderStatus.UNKNOWN: frozenset({OrderStatus.PAYING, OrderStatus.FAILED}),
    OrderStatus.VERIFYING: frozenset({OrderStatus.ACTIVE, OrderStatus.FAILED}),
    OrderStatus.ACTIVE: frozenset({OrderStatus.DELIVERED, OrderStatus.REFUNDED}),
    OrderStatus.DELIVERED: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.FAILED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}

#: 合法支付迁移表。
PAYMENT_TRANSITIONS: Dict[PaymentStatus, FrozenSet[PaymentStatus]] = {
    PaymentStatus.INITIATED: frozenset(
        {PaymentStatus.PROCESSING, PaymentStatus.DECLINED, PaymentStatus.ERROR}
    ),
    PaymentStatus.PROCESSING: frozenset(
        {
            PaymentStatus.SUCCEEDED,
            PaymentStatus.REQUIRES_ACTION,
            PaymentStatus.DECLINED,
            PaymentStatus.ERROR,
        }
    ),
    PaymentStatus.REQUIRES_ACTION: frozenset(
        {PaymentStatus.PROCESSING, PaymentStatus.DECLINED, PaymentStatus.ERROR}
    ),
    PaymentStatus.SUCCEEDED: frozenset(),
    PaymentStatus.DECLINED: frozenset(),
    PaymentStatus.ERROR: frozenset(),
}


class IllegalTransition(ValueError):
    """尝试进行未在迁移表中声明的状态迁移。"""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"illegal transition: {current} -> {target}")
        self.current = current
        self.target = target


def can_transition(
    current: OrderStatus, target: OrderStatus, table: Dict = ORDER_TRANSITIONS
) -> bool:
    """判断迁移是否合法（不抛异常）。"""

    return target in table[current]


def assert_transition(
    current: OrderStatus, target: OrderStatus, table: Dict = ORDER_TRANSITIONS
) -> None:
    """校验迁移合法，否则抛 :class:`IllegalTransition`。"""

    if not can_transition(current, target, table):
        raise IllegalTransition(str(current), str(target))


def is_terminal(status: OrderStatus) -> bool:
    """是否为终态。"""

    return status in TERMINAL_ORDER_STATUSES


def is_deliverable(status: OrderStatus) -> bool:
    """是否允许交付（必须订阅已确认生效）。"""

    return status in DELIVERABLE_ORDER_STATUSES


__all__ = [
    "OrderStatus",
    "PaymentStatus",
    "ORDER_TRANSITIONS",
    "PAYMENT_TRANSITIONS",
    "TERMINAL_ORDER_STATUSES",
    "DELIVERABLE_ORDER_STATUSES",
    "PENDING_ORDER_STATUSES",
    "IllegalTransition",
    "can_transition",
    "assert_transition",
    "is_terminal",
    "is_deliverable",
]
