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
    """真实 adapter：执行直卡绑定与支付（T025）。
    
    自己实现核心逻辑，参考 zkky 流程但不依赖其代码：
    1. 使用结账链接访问支付页面
    2. 提交卡片信息（payment_method_token 或平台卡池）
    3. 处理支付结果与 3DS 验证
    """

    upstream_path: Optional[str] = None
    timeout: int = 60

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def pay(self, req: PaymentRequest) -> PaymentResult:
        """执行卡支付（T025）。"""
        import httpx
        from dcp_core.redaction import redact_sensitive
        
        if not req.checkout_url:
            raise DomainError(
                ErrorCode.PAYMENT_DECLINED,
                "缺少 checkout_url，无法执行支付",
            )
        
        # 构建请求头
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Origin": "https://chatgpt.com",
            "Referer": req.checkout_url,
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                proxy=req.checkout_proxy if req.checkout_proxy else None,
                follow_redirects=True,
            ) as client:
                # 第一步：获取结账会话信息
                checkout_response = await client.get(
                    req.checkout_url,
                    headers=headers,
                )
                
                if checkout_response.status_code >= 400:
                    raise DomainError(
                        ErrorCode.PAYMENT_UNKNOWN_STATE,
                        f"访问结账链接失败: HTTP {checkout_response.status_code}",
                    )
                
                # 提取 checkout session ID（从 URL 或响应中）
                # 实际实现需要解析页面或从 cookies 获取
                session_id = self._extract_session_id(checkout_response)
                
                # 第二步：提交支付信息
                payment_payload = {
                    "checkout_session_id": session_id,
                    "country": req.country,
                }
                
                # 根据 card_source 选择不同的支付方式
                if req.payment_method_token:
                    # 客户提供的卡（浏览器端 Stripe.js 产出的 token）
                    payment_payload["payment_method_token"] = req.payment_method_token
                elif req.card_id:
                    # 平台卡池（使用预存的卡 ID）
                    payment_payload["card_id"] = req.card_id
                else:
                    raise DomainError(
                        ErrorCode.PAYMENT_DECLINED,
                        "缺少支付方式：需要 payment_method_token 或 card_id",
                    )
                
                # 使用支付代理（approve 阶段）
                pay_client = httpx.AsyncClient(
                    timeout=self.timeout,
                    proxy=req.approve_proxy if req.approve_proxy else None,
                    follow_redirects=False,  # 需要捕获 3DS 重定向
                )
                
                async with pay_client:
                    pay_response = await pay_client.post(
                        f"{self._get_payment_endpoint(req.checkout_url)}",
                        json=payment_payload,
                        headers=headers,
                    )
                    
                    # 处理支付响应
                    if pay_response.status_code == 302 or pay_response.status_code == 303:
                        # 3DS 重定向
                        redirect_url = pay_response.headers.get("Location")
                        return PaymentResult(
                            status=PaymentStatus.REQUIRES_ACTION,
                            next_action={
                                "type": "3ds_redirect",
                                "url": redirect_url,
                            },
                            provider_ref=session_id,
                            message="需要完成 3DS 验证",
                        )
                    
                    if pay_response.status_code >= 500:
                        # 服务端错误，状态未知
                        return PaymentResult(
                            status=PaymentStatus.ERROR,
                            next_action=None,
                            provider_ref=session_id,
                            message=f"支付服务错误: {pay_response.status_code}",
                        )
                    
                    if pay_response.status_code == 402 or pay_response.status_code == 400:
                        # 支付被拒
                        error_data = pay_response.json() if pay_response.content else {}
                        return PaymentResult(
                            status=PaymentStatus.DECLINED,
                            next_action=None,
                            provider_ref=session_id,
                            message=redact_sensitive(error_data.get("message", "支付被拒绝")),
                        )
                    
                    # 解析支付结果
                    pay_data = pay_response.json()
                    payment_status = pay_data.get("status", "unknown")
                    
                    if payment_status in ["succeeded", "active", "completed"]:
                        return PaymentResult(
                            status=PaymentStatus.SUCCEEDED,
                            next_action=None,
                            provider_ref=pay_data.get("payment_id", session_id),
                            message="支付成功",
                        )
                    elif payment_status in ["processing", "pending"]:
                        return PaymentResult(
                            status=PaymentStatus.PROCESSING,
                            next_action=None,
                            provider_ref=pay_data.get("payment_id", session_id),
                            message="支付处理中",
                        )
                    elif payment_status in ["failed", "declined"]:
                        return PaymentResult(
                            status=PaymentStatus.DECLINED,
                            next_action=None,
                            provider_ref=pay_data.get("payment_id", session_id),
                            message=redact_sensitive(pay_data.get("message", "支付失败")),
                        )
                    else:
                        # 未知状态
                        return PaymentResult(
                            status=PaymentStatus.ERROR,
                            next_action=None,
                            provider_ref=pay_data.get("payment_id", session_id),
                            message=f"未知支付状态: {payment_status}",
                        )
                        
        except httpx.TimeoutException:
            raise DomainError(
                ErrorCode.PAYMENT_UNKNOWN_STATE,
                f"支付请求超时（{self.timeout}s），状态未知",
            )
        except httpx.RequestError as e:
            raise DomainError(
                ErrorCode.PAYMENT_UNKNOWN_STATE,
                f"网络请求失败: {redact_sensitive(str(e))}",
            )
    
    def _extract_session_id(self, response: "httpx.Response") -> str:
        """从结账响应中提取 session ID。"""
        # 简化实现：从 URL 参数或 cookies 提取
        # 实际需要根据 ChatGPT 的具体实现调整
        import re
        url = str(response.url)
        match = re.search(r'/checkout/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        return "unknown-session"
    
    def _get_payment_endpoint(self, checkout_url: str) -> str:
        """根据结账 URL 构建支付端点。"""
        # 实际需要根据 ChatGPT 的 API 结构调整
        return checkout_url.replace("/checkout/", "/payments/complete/")


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
