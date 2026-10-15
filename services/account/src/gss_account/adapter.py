"""订阅校验。交付前必须确认订阅已生效。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from gss_contracts import AdapterCapabilities, SubscriptionInfo
from gss_contracts.errors import DomainError, ErrorCode
from gss_core.chatgpt import ChatGPTClient
from gss_core.proxies import configured_proxy

_ACTIVE_PLANS = {
    "plus",
    "chatgptplusplan",
    "go",
    "chatgptgoplan",
    "pro",
    "chatgptpro",
    "chatgptproplan",
    "pro_lite",
    "chatgptprolite",
    "chatgptpromax",
    "pro_max",
    "team",
    "chatgptteamplan",
    "enterprise",
    "active",
    "trialing",
    "paid",
}


class AccountAdapterBase:
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            source="self-contained chatgpt.com backend-api/subscriptions",
            license="MIT (this repository)",
            supports={
                "account_sources": ["customer_session"],
                "actions": ["subscription_status"],
            },
            failure_modes={
                "invalid_session": "session 无效 → 重新粘贴",
                "subscription_not_active": "订阅未生效 → 确认窗口内重试，不交付",
            },
        )


@dataclass
class UpstreamAccountAdapter(AccountAdapterBase):
    timeout: int = 30

    async def subscription_status(self, session: str) -> SubscriptionInfo:
        if not session:
            raise DomainError(ErrorCode.INVALID_SESSION, "缺少 session，无法查询订阅")
        client = ChatGPTClient.from_raw_session(session, proxy=configured_proxy("checkout"))
        client.timeout = float(self.timeout)
        payload = client.subscription_payload()
        plan_type = str(
            payload.get("plan_type")
            or (payload.get("subscription") or {}).get("plan")
            or (payload.get("plan") or {}).get("type")
            or ""
        ).lower()
        status = str(
            (payload.get("subscription") or {}).get("status")
            or payload.get("status")
            or ""
        ).lower()
        is_active = plan_type in _ACTIVE_PLANS or status in {"active", "trialing", "paid"}
        expires_at = None
        expires_raw = (
            (payload.get("subscription") or {}).get("expires_at")
            or payload.get("expires_at")
        )
        if isinstance(expires_raw, str) and expires_raw:
            try:
                expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        return SubscriptionInfo(
            active=is_active,
            expires_at=expires_at,
            channel="card" if is_active else None,
            raw_kind=plan_type or status or "unknown",
        )

    async def register_account(self) -> Dict[str, Any]:
        raise NotImplementedError("本工具只开通客户自己的账号，不代注册")


@dataclass
class FakeAccountAdapter(AccountAdapterBase):
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
            expires_at=(datetime.now(timezone.utc) + timedelta(days=30) if self.active else None),
            channel="web" if self.active else None,
            raw_kind="fake",
        )

    async def register_account(self) -> Dict[str, Any]:
        return {"session": "fake-session", "email": "fake@example.invalid"}


__all__ = ["AccountAdapterBase", "UpstreamAccountAdapter", "FakeAccountAdapter"]
