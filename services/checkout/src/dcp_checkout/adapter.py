"""结账链接生成能力（adapter）。

上游：`2951461586/GPT-Register-Tool` 的 ``direct_card`` 提链（**无 LICENSE**）。
本模块只定义接口与离线 fake，**不复制上游代码**（ADR 0001）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from dcp_contracts import (
    AdapterCapabilities,
    BillingMode,
    CheckoutRequest,
    CheckoutResult,
    Plan,
)
from dcp_contracts.errors import DomainError, ErrorCode

#: 上游目录环境变量（见 deploy/.env.example）。
ENV_UPSTREAM_PATH = "UPSTREAM_GPT_REGISTER_TOOL_PATH"

_CURRENCY_BY_COUNTRY = {"US": "USD", "JP": "JPY", "PH": "PHP", "GB": "GBP"}
_STANDARD_PRICE = Decimal("20.00")


class CheckoutAdapterBase:
    """checkout adapter 的公共能力声明。"""

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="2951461586/GPT-Register-Tool@direct_card",
            license="NO-LICENSE (all rights reserved) — 仅 adapter 引用，不复制",
            supports={
                "plans": [p.value for p in Plan],
                "billing_modes": [m.value for m in BillingMode],
                "countries": sorted(_CURRENCY_BY_COUNTRY),
            },
            failure_modes={
                "billing_country_mismatch": "代理出口国家与账单国家不一致 → 改配置后重试",
                "unusual_activity": "上游拒绝创建结账 → 重试一次，再失败转人工",
                "session_expired": "401 → 需重新导出 session",
                "cloudflare_403": "代理节点被拦 → 换节点后重试",
            },
        )


@dataclass
class UpstreamCheckoutAdapter(CheckoutAdapterBase):
    """真实 adapter：调用上游提链脚本/模块。

    骨架阶段：未配置上游路径时fail-fast 抛 ``checkout_upstream_error``，
    已配置时抛 ``NotImplementedError`` 指向实现任务，避免静默给出假链接。
    """

    upstream_path: Optional[str] = None

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        if not self.upstream_path:
            raise DomainError(
                ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                f"未配置 {ENV_UPSTREAM_PATH}，无法调用上游提链",
            )
        raise NotImplementedError(
            "骨架阶段：真实提链实现见 docs/upstream-integration.md 与 tasks.md T019"
        )


@dataclass
class FakeCheckoutAdapter(CheckoutAdapterBase):
    """离线测试用 adapter（宪法第 V 条）。"""

    calls: List[CheckoutRequest] = field(default_factory=list)

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        self.calls.append(req)
        currency = _CURRENCY_BY_COUNTRY.get(req.billing_country, "USD")
        amount = (
            Decimal("0.00")
            if req.billing_mode is BillingMode.PROMO
            else _STANDARD_PRICE
        )
        return CheckoutResult(
            checkout_url=f"https://chatgpt.com/checkout/fake/{len(self.calls)}",
            plan=req.plan,
            currency=currency,
            amount=amount,
            upstream_request_id="fake-checkout-req",
        )


__all__ = ["CheckoutAdapterBase", "UpstreamCheckoutAdapter", "FakeCheckoutAdapter"]
