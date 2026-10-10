"""卡支付。浏览器只提交 PaymentMethod 标识，本模块向 Stripe / ChatGPT 确认。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dcp_contracts import AdapterCapabilities, PaymentRequest, PaymentResult, PaymentStatus
from dcp_contracts.errors import DomainError, ErrorCode
from dcp_core.billing import address_for
from dcp_core.chatgpt import (
    APP_BASE,
    ChatGPTClient,
    checkout_confirm_blocked,
    checkout_confirm_blocked_advice,
    checkout_confirm_message,
    payment_intent_from_confirm,
)
from dcp_core.countries import currency_for, locale_for, timezone_for
from dcp_core.proxies import align_proxy_region, configured_proxy, session_proxy


class PaymentAdapterBase:
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="self-contained chatgpt.com + api.stripe.com",
            license="MIT (this repository)",
            supports={
                "providers": ["direct_card"],
                "card_sources": ["customer"],
                "proxy_roles": ["checkout", "approve"],
            },
            failure_modes={
            "payment_declined": "卡片被拒或 ChatGPT 风控 blocked → 换卡 / 整段 session 后重试",
            "requires_action": "3DS → 在浏览器完成验证",
            "payment_unknown_state": "终态不确定 → 先查订阅，避免重复扣款",
            },
        )


@dataclass
class UpstreamPaymentAdapter(PaymentAdapterBase):
    timeout: int = 120

    async def pay(self, req: PaymentRequest) -> PaymentResult:
        if not req.payment_method_token and not req.card_id:
            raise DomainError(
                ErrorCode.PAYMENT_DECLINED,
                "缺少支付方式：需要浏览器端 payment_method_token",
            )
        if not req.session:
            raise DomainError(ErrorCode.INVALID_SESSION, "支付阶段缺少 session")
        checkout_id = req.checkout_session_id or ""
        if not checkout_id:
            raise DomainError(ErrorCode.PAYMENT_DECLINED, "缺少 checkout_session_id")

        proxy = align_proxy_region(
            req.checkout_proxy
            or req.approve_proxy
            or session_proxy("checkout", req.country)
            or configured_proxy("checkout")
            or configured_proxy("approve"),
            req.country,
        )
        client = ChatGPTClient.from_raw_session(req.session, proxy=proxy)
        client.timeout = float(self.timeout)
        client.language = locale_for(req.country)
        client.timezone = timezone_for(req.country)
        page_url = req.checkout_url if str(req.checkout_url or "").startswith(APP_BASE) else f"{APP_BASE}/"
        client.warmup(page_url=page_url)
        pk = req.publishable_key or ""
        if not pk:
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "缺少 Stripe 公钥")

        billing = dict(req.billing or address_for(req.country))
        confirm_token = _confirmation_token(
            client, publishable_key=pk, token=req.payment_method_token or ""
        )
        confirmed = client.confirm_checkout(
            checkout_session_id=checkout_id,
            confirm_token=confirm_token,
            checkout_url=page_url,
            billing=billing,
            currency=currency_for(req.country),
        )
        intent_id, intent_secret, return_url = payment_intent_from_confirm(confirmed)
        chatgpt_status = str(confirmed.get("status") or "")
        kind = str(confirmed.get("type") or "")
        if checkout_confirm_blocked(confirmed):
            extra = checkout_confirm_message(confirmed)
            advice = checkout_confirm_blocked_advice(req.country)
            return PaymentResult(
                status=PaymentStatus.DECLINED,
                provider_ref=intent_id or checkout_id,
                message=f"{extra}。{advice}" if extra else advice,
            )
        if intent_secret.startswith("pi_") or kind == "payment_intent" or intent_id.startswith("pi_"):
            if not return_url:
                return_url = f"{APP_BASE}/checkout/verify?stripe_session_id={checkout_id}"
            final = client.confirm_stripe_intent(
                intent_id=intent_id,
                client_secret=intent_secret,
                publishable_key=pk,
                confirmation_token=confirm_token,
                return_url=return_url,
            )
            return _result_from_intent(final, intent_id)
        if chatgpt_status in {"succeeded", "success", "complete", "completed"}:
            return PaymentResult(
                status=PaymentStatus.SUCCEEDED,
                provider_ref=intent_id or checkout_id,
                message="支付成功",
            )
        return PaymentResult(
            status=PaymentStatus.ERROR,
            provider_ref=intent_id or checkout_id,
            message=f"未知支付状态: {chatgpt_status or 'empty'}",
        )


def _confirmation_token(client: ChatGPTClient, *, publishable_key: str, token: str) -> str:
    text = str(token or "").strip()
    if text.startswith("ctoken_"):
        return text
    if text.startswith("pm_"):
        return client.create_confirmation_token(publishable_key=publishable_key, payment_method=text)
    raise DomainError(ErrorCode.PAYMENT_DECLINED, "支付标识无效")


def _result_from_intent(payload: Dict[str, Any], intent_id: str) -> PaymentResult:
    status = str(payload.get("status") or "")
    if status == "requires_action":
        next_action = payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {}
        return PaymentResult(
            status=PaymentStatus.REQUIRES_ACTION,
            next_action={
                "type": "3ds_redirect",
                "url": (next_action or {}).get("redirect_to_url", {}).get("url")
                or (next_action or {}).get("url"),
            },
            provider_ref=intent_id,
            message="需要完成 3DS 验证",
        )
    if status == "succeeded":
        return PaymentResult(status=PaymentStatus.SUCCEEDED, provider_ref=intent_id, message="支付成功")
    if status in {"processing", "pending"}:
        return PaymentResult(status=PaymentStatus.PROCESSING, provider_ref=intent_id, message="支付处理中")
    return PaymentResult(
        status=PaymentStatus.ERROR,
        provider_ref=intent_id,
        message=f"未知支付状态: {status or 'empty'}",
    )


@dataclass
class FakePaymentAdapter(PaymentAdapterBase):
    scripted: List[PaymentStatus] = field(default_factory=lambda: [PaymentStatus.SUCCEEDED])
    calls: List[PaymentRequest] = field(default_factory=list)

    async def pay(self, req: PaymentRequest) -> PaymentResult:
        self.calls.append(req)
        if not self.scripted:
            raise AssertionError("FakePaymentAdapter 脚本已耗尽")
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
