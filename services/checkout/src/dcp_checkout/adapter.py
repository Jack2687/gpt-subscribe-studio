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
    """真实 adapter：生成 ChatGPT 直卡结账链接。

    自己实现核心逻辑，参考上游流程但不依赖其代码：
    1. 使用 session 访问 ChatGPT 后台
    2. 创建 direct_card 支付方式的结账链接
    3. 返回托管结账 URL 供后续绑卡支付
    """

    upstream_path: Optional[str] = None
    timeout: int = 30

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        """生成结账链接（T019）。"""
        import httpx
        from dcp_core.redaction import redact_sensitive
        
        if not req.session:
            raise DomainError(
                ErrorCode.INVALID_SESSION,
                "缺少 session，无法创建结账链接",
            )
        
        # ChatGPT 订阅 API 端点
        api_base = "https://chatgpt.com/backend-api"
        
        # 构建请求头
        headers = {
            "Authorization": f"Bearer {req.session}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        
        # 根据套餐映射到 ChatGPT 的产品 ID
        plan_mapping = {
            Plan.PLUS: "chatgpt_plus",
            Plan.PRO_LITE: "chatgpt_pro_lite",
            Plan.PRO: "chatgpt_pro",
            Plan.PRO_MAX: "chatgpt_pro_max",
        }
        
        product_id = plan_mapping.get(req.plan, "chatgpt_plus")
        
        # 构建结账请求
        checkout_payload = {
            "product_id": product_id,
            "payment_method": "direct_card",
            "billing_country": req.billing_country,
            "is_promotional": req.billing_mode == BillingMode.PROMO,
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=req.proxy if req.proxy else None,
            ) as client:
                # 创建结账会话
                response = await client.post(
                    f"{api_base}/payments/checkout",
                    json=checkout_payload,
                    headers=headers,
                )
                
                if response.status_code == 401:
                    raise DomainError(
                        ErrorCode.INVALID_SESSION,
                        "Session 已失效或无效",
                    )
                elif response.status_code == 403:
                    raise DomainError(
                        ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                        "请求被拦截（可能是 Cloudflare），请更换代理",
                    )
                elif response.status_code >= 400:
                    error_msg = redact_sensitive(response.text)
                    raise DomainError(
                        ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                        f"创建结账失败: HTTP {response.status_code} - {error_msg}",
                    )
                
                data = response.json()
                
                # 提取结账链接
                checkout_url = data.get("checkout_url") or data.get("url")
                if not checkout_url:
                    raise DomainError(
                        ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                        f"上游响应缺少 checkout_url: {redact_sensitive(str(data))}",
                    )
                
                # 提取金额信息
                amount = Decimal(str(data.get("amount", "20.00")))
                currency = data.get("currency", _CURRENCY_BY_COUNTRY.get(req.billing_country, "USD"))
                
                return CheckoutResult(
                    checkout_url=checkout_url,
                    plan=req.plan,
                    currency=currency,
                    amount=amount,
                    upstream_request_id=data.get("request_id", ""),
                )
                
        except httpx.TimeoutException:
            raise DomainError(
                ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                f"请求超时（{self.timeout}s），请检查网络或代理",
            )
        except httpx.RequestError as e:
            raise DomainError(
                ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                f"网络请求失败: {redact_sensitive(str(e))}",
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
