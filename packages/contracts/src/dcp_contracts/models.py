"""领域模型与模式开关。

宪法第 I 条：本模块的实体**不得**包含 session / token / 卡号 / CVV / 代理明文口令。
宪法第 IV 条：三个模式开关必须显式建模，默认 ``standard`` + ``customer`` + ``customer_session``。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional

from .state import OrderStatus, PaymentStatus

try:  # Python 3.11+
    from enum import StrEnum
except ImportError:  # Python 3.9 / 3.10 兼容
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        def __str__(self) -> str:
            return str(self.value)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Plan(StrEnum):
    """订阅档位。"""

    PLUS = "plus"
    PRO_LITE = "pro_lite"
    PRO = "pro"
    PRO_MAX = "pro_max"


class AccountSource(StrEnum):
    """账号来源。"""

    CUSTOMER_SESSION = "customer_session"
    PLATFORM_ACCOUNT = "platform_account"


class CardSource(StrEnum):
    """卡片来源。"""

    CUSTOMER = "customer"
    PLATFORM = "platform"


class BillingMode(StrEnum):
    """计费模式。``promo`` 属高风险，默认关闭。"""

    STANDARD = "standard"
    PROMO = "promo"


class ModeValidationError(ValueError):
    """模式组合非法。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Mode:
    """三个正交模式开关。"""

    account_source: AccountSource = AccountSource.CUSTOMER_SESSION
    card_source: CardSource = CardSource.CUSTOMER
    billing_mode: BillingMode = BillingMode.STANDARD
    risk_acknowledged: bool = False

    def validate(self) -> None:
        """校验模式组合；不合法时抛 :class:`ModeValidationError`。"""

        if self.billing_mode is BillingMode.PROMO and not self.risk_acknowledged:
            raise ModeValidationError(
                "promo_not_acknowledged",
                "billing_mode=promo 需要显式确认风险（risk_acknowledged=true）",
            )
        if (
            self.account_source is AccountSource.CUSTOMER_SESSION
            and self.card_source is CardSource.PLATFORM
            and self.billing_mode is BillingMode.PROMO
        ):
            raise ModeValidationError(
                "promo_platform_card_on_customer_account",
                "客户账号 + 平台卡 + 促销 组合不受支持，请改用 standard",
            )

    @property
    def is_high_risk(self) -> bool:
        """是否为高风险组合（用于 UI 与合规双重标注）。"""

        return self.billing_mode is BillingMode.PROMO


@dataclass
class Order:
    """开通订单。**不含任何凭证字段。**"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str = ""
    plan: Plan = Plan.PLUS
    billing_country: str = ""
    mode: Mode = field(default_factory=Mode)
    status: OrderStatus = OrderStatus.CREATED
    amount: Optional[Decimal] = None
    cost: Optional[Decimal] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class Job:
    """编排任务。支持断点续跑（占锁）。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = ""
    stage: str = "checkout"
    attempts: int = 0
    locked_by: Optional[str] = None
    locked_at: Optional[datetime] = None
    last_error: Optional[str] = None  # 必须已脱敏
    checkout_url: Optional[str] = None


@dataclass
class PaymentAttempt:
    """一次支付尝试。``next_action`` 为不透明数据。"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = ""
    provider: str = "direct_card"
    status: PaymentStatus = PaymentStatus.INITIATED
    next_action: Optional[Dict[str, Any]] = None
    proxy_role: Optional[str] = None


@dataclass
class PlatformCard:
    """平台卡池条目。**使用标识而非卡号。**"""

    id: str = ""
    pool: str = "default"
    status: str = "available"
    usage_audit: list = field(default_factory=list)


@dataclass
class ProxyPool:
    """代理池。提链池与支付池必须独立保存，互不覆盖。"""

    role: str = "checkout"
    entries: list = field(default_factory=list)  # 已脱敏
    stage_countries: Dict[str, str] = field(default_factory=dict)


__all__ = [
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
]
