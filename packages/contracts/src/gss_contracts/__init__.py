"""共享契约包：状态机、领域模型、错误码、adapter 协议。

见 ``docs/adr/0001-upstream-adapter-boundary.md`` 与 ADR 0002。
"""

from __future__ import annotations

from .adapter import (
    AccountAdapter,
    AdapterCapabilities,
    CheckoutAdapter,
    CheckoutRequest,
    CheckoutResult,
    PaymentAdapter,
    PaymentRequest,
    PaymentResult,
    PromoCampaignInfo,
    PromoEligibility,
    SubscriptionInfo,
)
from .errors import DomainError, ErrorCode
from .models import (
    AccountSource,
    BillingMode,
    CardSource,
    Job,
    Mode,
    ModeValidationError,
    Order,
    PaymentAttempt,
    Plan,
    PlatformCard,
    ProxyPool,
)
from .state import (
    DELIVERABLE_ORDER_STATUSES,
    ORDER_TRANSITIONS,
    PAYMENT_TRANSITIONS,
    PENDING_ORDER_STATUSES,
    TERMINAL_ORDER_STATUSES,
    IllegalTransition,
    OrderStatus,
    PaymentStatus,
    assert_transition,
    can_transition,
    is_deliverable,
    is_terminal,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # adapters
    "AdapterCapabilities",
    "CheckoutRequest",
    "CheckoutResult",
    "CheckoutAdapter",
    "PaymentRequest",
    "PaymentResult",
    "PaymentAdapter",
    "SubscriptionInfo",
    "PromoCampaignInfo",
    "PromoEligibility",
    "AccountAdapter",
    # errors
    "ErrorCode",
    "DomainError",
    # models
    "Plan",
    "AccountSource",
    "CardSource",
    "BillingMode",
    "Mode",
    "ModeValidationError",
    "Order",
    "Job",
    "PaymentAttempt",
    "PlatformCard",
    "ProxyPool",
    # state
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
