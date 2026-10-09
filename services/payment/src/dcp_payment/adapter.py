"""卡绑定与支付执行能力（adapter）。

上游：`alexan0618/zkky`（直卡开源，**MIT**）的直卡绑定与任务状态机。
宪法第 I 条：``payment_method_token`` / ``card_id`` 只作为入参在内存中流转，绝不落库。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dcp_contracts import (
    AdapterCapabilities,
    PaymentRequest,
    PaymentResult,
    PaymentStatus,
)
from dcp_contracts.errors import DomainError, ErrorCode

#: 上游目录环境变量（见 deploy/.env.example）。
ENV_UPSTREAM_PATH = "UPSTREAM_ZKKY_PATH"


class PaymentAdapterBase:
    """payment adapter 的公共能力声明。"""

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="alexan0618/zkky@standalone_core",
            license="MIT",
            supports={
                "providers": ["direct_card"],
                "card_sources": ["customer", "platform"],
                "proxy_roles": ["checkout", "approve"],
            },
            failure_modes={
                "payment_declined": "卡片被拒 → 永久失败",
                "requires_action": "3DS → 需客户在浏览器完成验证后回到 paying",
                "payment_unknown_state": "上游未给出确定终态 → 可重试，但必须先对账避免重复扣款",
                "payment_proxy_pool_unavailable": "支付代理不可用 → 换节点重试",
            },
        )


@dataclass
class UpstreamPaymentAdapter(PaymentAdapterBase):
    """真实 adapter：调用上游 zkky 直卡绑定。骨架阶段 fail-fast。"""

    upstream_path: Optional[str] = None

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def pay(self, req: PaymentRequest) -> PaymentResult:
        if not self.upstream_path:
            raise DomainError(
                ErrorCode.PAYMENT_UNKNOWN_STATE,
                f"未配置 {ENV_UPSTREAM_PATH}，无法执行卡绑定支付",
            )
        raise NotImplementedError(
            "骨架阶段：真实实现见 docs/upstream-integration.md 与 tasks.md T025"
        )


@dataclass
class FakePaymentAdapter(PaymentAdapterBase):
    """离线测试用 adapter：按脚本返回支付状态（宪法第 V 条）。"""

    scripted: List[PaymentStatus] = field(
        default_factory=lambda: [PaymentStatus.SUCCEEDED]
    )
    calls: List[PaymentRequest] = field(default_factory=list)

    async def pay(self, req: PaymentRequest) -> PaymentResult:
        self.calls.append(req)
        if not self.scripted:
            raise AssertionError("FakePaymentAdapter 脚本已耗尽（请显式声明期望序列）")
        status = self.scripted.pop(0)
        next_action: Optional[Dict[str, Any]] = None
        if status is PaymentStatus.REQUIRES_ACTION:
            next_action = {"type": "3ds_redirect", "url": "https://3ds.example.invalid/verify"}
        return PaymentResult(
            status=status,
            next_action=next_action,
            provider_ref="fake-payment-ref",
            message=f"scripted:{status}",
        )


__all__ = ["PaymentAdapterBase", "UpstreamPaymentAdapter", "FakePaymentAdapter"]
