"""账号能力（adapter）。

上游：`2951461586/GPT-Register-Tool` 的注册引擎与账号/订阅查询（**无 LICENSE**）。
交付前必须调用 :meth:`subscription_status` 确认订阅已生效（FR-006 / SC-003）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from dcp_contracts import AdapterCapabilities, SubscriptionInfo
from dcp_contracts.errors import DomainError, ErrorCode

#: 上游目录环境变量（见 deploy/.env.example）。
ENV_UPSTREAM_PATH = "UPSTREAM_GPT_REGISTER_TOOL_PATH"


class AccountAdapterBase:
    """account adapter 的公共能力声明。"""

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="2951461586/GPT-Register-Tool@registration",
            license="NO-LICENSE (all rights reserved) — 仅 adapter 引用，不复制",
            supports={
                "account_sources": ["customer_session", "platform_account"],
                "mailboxes": ["remail", "cfworker", "graph", "gmail", "icloud_url"],
                "actions": ["register", "subscription_status"],
            },
            failure_modes={
                "invalid_session": "session 无效 → 需客户重新导出",
                "session_expired": "session 过期 → 401 分层恢复后重试",
                "account_deactivated": "账号被封 → 永久失败，不反复重登",
                "subscription_not_active": "订阅未生效 → 在确认窗口内重试，不交付",
            },
        )


@dataclass
class UpstreamAccountAdapter(AccountAdapterBase):
    """真实 adapter：查询 ChatGPT 账号订阅状态（T031）。
    
    自己实现核心逻辑：
    1. 使用 session 访问 ChatGPT 账号 API
    2. 查询当前订阅状态与到期时间
    3. 确认订阅已生效才允许交付
    """

    upstream_path: Optional[str] = None
    timeout: int = 30

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def subscription_status(self, session: str) -> SubscriptionInfo:
        """查询订阅状态（T031：交付前必须调用）。"""
        import httpx
        from dcp_core.redaction import redact_sensitive
        
        if not session:
            raise DomainError(
                ErrorCode.INVALID_SESSION,
                "缺少 session，无法查询订阅状态",
            )
        
        # ChatGPT 账号 API 端点
        api_base = "https://chatgpt.com/backend-api"
        
        headers = {
            "Authorization": f"Bearer {session}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            ) as client:
                # 查询账号信息（包含订阅状态）
                response = await client.get(
                    f"{api_base}/me",
                    headers=headers,
                )
                
                if response.status_code == 401:
                    raise DomainError(
                        ErrorCode.INVALID_SESSION,
                        "Session 已失效，需重新登录",
                    )
                elif response.status_code >= 400:
                    error_msg = redact_sensitive(response.text)
                    raise DomainError(
                        ErrorCode.SUBSCRIPTION_NOT_ACTIVE,
                        f"查询订阅失败: HTTP {response.status_code} - {error_msg}",
                    )
                
                data = response.json()
                
                # 解析订阅信息
                # ChatGPT API 返回结构（实际可能需要调整）：
                # {
                #   "subscription": {
                #     "plan": "chatgpt_plus",
                #     "status": "active",
                #     "expires_at": "2026-11-09T00:00:00Z",
                #     "payment_method": "card"
                #   }
                # }
                
                subscription = data.get("subscription", {})
                plan_info = data.get("plan", {})
                
                # 判断订阅是否生效
                status = subscription.get("status") or plan_info.get("status")
                is_active = status in ["active", "trialing", "paid"]
                
                # 提取到期时间
                expires_at_str = subscription.get("expires_at") or plan_info.get("expires_at")
                expires_at = None
                if expires_at_str:
                    try:
                        from datetime import datetime
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        pass
                
                # 提取购买渠道
                channel = subscription.get("payment_method") or subscription.get("channel", "web")
                
                # 提取订阅类型
                plan_type = subscription.get("plan") or plan_info.get("type", "unknown")
                
                return SubscriptionInfo(
                    active=is_active,
                    expires_at=expires_at,
                    channel=channel if is_active else None,
                    raw_kind=plan_type,
                )
                
        except httpx.TimeoutException:
            raise DomainError(
                ErrorCode.SUBSCRIPTION_NOT_ACTIVE,
                f"查询订阅超时（{self.timeout}s），请稍后重试",
            )
        except httpx.RequestError as e:
            raise DomainError(
                ErrorCode.SUBSCRIPTION_NOT_ACTIVE,
                f"网络请求失败: {redact_sensitive(str(e))}",
            )

    async def register_account(self) -> Dict[str, Any]:
        """账号注册（T035：平台账号库存）。"""
        raise NotImplementedError("账号注册功能暂未实现，见 tasks.md T035")


@dataclass
class FakeAccountAdapter(AccountAdapterBase):
    """离线测试用 adapter。``active=False`` 可模拟「支付成功但订阅未生效」。"""

    active: bool = True
    sessions_seen: Optional[list] = None

    def __post_init__(self) -> None:
        if self.sessions_seen is None:
            self.sessions_seen = []

    async def subscription_status(self, session: str) -> SubscriptionInfo:
        assert self.sessions_seen is not None
        self.sessions_seen.append(session)
        return SubscriptionInfo(
            active=self.active,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=30) if self.active else None
            ),
            channel="web" if self.active else None,
            raw_kind="fake",
        )

    async def register_account(self) -> Dict[str, Any]:
        return {"session": "fake-session", "email": "fake@example.invalid"}


__all__ = ["AccountAdapterBase", "UpstreamAccountAdapter", "FakeAccountAdapter"]
