"""结账能力。独立实现，直接请求 ChatGPT，不依赖其它本地项目。"""

from __future__ import annotations

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
from dcp_core.billing import address_for
from dcp_core.chatgpt import ChatGPTClient, clamp_team_seats
from dcp_core.countries import country_codes, currency_for
from dcp_core.proxies import align_proxy_region, configured_proxy, rotate_proxy_sid, session_proxy

_LIST_PRICE = {
    Plan.PLUS: Decimal("20.00"),
    Plan.PRO_LITE: Decimal("20.00"),
    Plan.PRO: Decimal("200.00"),
    Plan.PRO_MAX: Decimal("200.00"),
    Plan.TEAM: Decimal("125.00"),
}


class CheckoutAdapterBase:
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="self-contained chatgpt.com payments/checkout",
            license="MIT (this repository)",
            supports={
                "plans": [p.value for p in Plan],
                "billing_modes": [m.value for m in BillingMode],
                "countries": country_codes(),
            },
            failure_modes={
                "session_expired": "401 → 重新粘贴 session",
                "cloudflare_403": "被拦 → 换与账单国家一致的出口代理",
                "unusual_activity": "上游判定异常流量 → 换 SID 或同国家新 session",
                "sentinel_missing": "无法签发 Sentinel → 检查 Node 与出口代理",
            },
        )


@dataclass
class UpstreamCheckoutAdapter(CheckoutAdapterBase):
    """用客户 session 向 ChatGPT 创建结账会话，并取出 Stripe 公钥。"""

    timeout: int = 120

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        if not req.session:
            raise DomainError(ErrorCode.INVALID_SESSION, "缺少 session，无法创建结账")
        proxy = align_proxy_region(
            req.proxy or session_proxy("checkout", req.billing_country) or configured_proxy("checkout"),
            req.billing_country,
        )
        try:
            created = self._create(req, proxy)
        except DomainError as exc:
            if exc.code is not ErrorCode.CHECKOUT_UPSTREAM_ERROR or "异常流量" not in str(exc):
                raise
            rotated = rotate_proxy_sid(proxy or "")
            if not rotated or rotated == proxy:
                raise
            created = self._create(req, rotated)
        amount = created.amount
        if amount is None:
            amount = Decimal("0.00") if req.billing_mode is BillingMode.PROMO else _list_price(req)
        return CheckoutResult(
            checkout_url=created.checkout_url,
            plan=req.plan,
            currency=created.currency,
            amount=amount,
            upstream_request_id=created.checkout_session_id,
            checkout_session_id=created.checkout_session_id,
            publishable_key=created.publishable_key or None,
            customer_session_client_secret=created.customer_session_client_secret or None,
            billing=dict(address_for(req.billing_country)),
            checkout_kind=created.checkout_kind or ("hosted" if req.plan is Plan.TEAM else "custom"),
        )

    def _create(self, req: CheckoutRequest, proxy: Optional[str]):
        client = ChatGPTClient.from_raw_session(req.session, proxy=proxy)
        client.timeout = float(self.timeout)
        try:
            return client.create_checkout(
                plan=str(req.plan),
                country=req.billing_country,
                promo=req.billing_mode is BillingMode.PROMO,
                promo_code=req.promo_code,
                workspace_name=req.workspace_name,
                seat_quantity=req.seat_quantity,
                price_interval=req.price_interval,
            )
        finally:
            client.close()


@dataclass
class FakeCheckoutAdapter(CheckoutAdapterBase):
    calls: List[CheckoutRequest] = field(default_factory=list)

    async def create_checkout(self, req: CheckoutRequest) -> CheckoutResult:
        self.calls.append(req)
        currency = currency_for(req.billing_country)
        amount = Decimal("0.00") if req.billing_mode is BillingMode.PROMO else _list_price(req)
        hosted = req.plan is Plan.TEAM
        return CheckoutResult(
            checkout_url=(
                f"https://pay.openai.com/c/pay/cs_test_fake_{len(self.calls)}"
                if hosted
                else f"https://chatgpt.com/checkout/fake/{len(self.calls)}"
            ),
            plan=req.plan,
            currency=currency,
            amount=amount,
            upstream_request_id="fake-checkout-req",
            checkout_session_id=(
                f"cs_test_fake_{len(self.calls)}" if hosted else f"oaics_fake_{len(self.calls)}"
            ),
            publishable_key=None,
            billing=dict(address_for(req.billing_country)),
            checkout_kind="hosted" if hosted else "custom",
        )


def _list_price(req: CheckoutRequest) -> Decimal:
    if req.plan is Plan.TEAM:
        seats = clamp_team_seats(req.seat_quantity)
        return Decimal(str(25 * seats))
    return _LIST_PRICE.get(req.plan, Decimal("20.00"))


__all__ = ["CheckoutAdapterBase", "UpstreamCheckoutAdapter", "FakeCheckoutAdapter"]
