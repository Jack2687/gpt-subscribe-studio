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
    """真实 adapter：调用上游注册/查询能力。骨架阶段 fail-fast。"""

    upstream_path: Optional[str] = None

    def __post_init__(self) -> None:
        self.upstream_path = self.upstream_path or os.environ.get(ENV_UPSTREAM_PATH)

    async def subscription_status(self, session: str) -> SubscriptionInfo:
        if not self.upstream_path:
            raise DomainError(
                ErrorCode.SUBSCRIPTION_NOT_ACTIVE,
                f"未配置 {ENV_UPSTREAM_PATH}，无法校验订阅状态",
            )
        raise NotImplementedError(
            "骨架阶段：真实实现见 docs/upstream-integration.md 与 tasks.md T031"
        )

    async def register_account(self) -> Dict[str, Any]:
        raise NotImplementedError("骨架阶段：见 tasks.md T035")


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
