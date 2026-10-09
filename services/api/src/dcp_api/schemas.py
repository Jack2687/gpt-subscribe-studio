"""请求 / 响应 schema（FastAPI / pydantic v2）。

与 `specs/001-subscribe-console/contracts/openapi.yaml` 保持一致。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ModeIn(BaseModel):
    """三个正交模式开关。"""

    account_source: str = Field(default="customer_session")
    card_source: str = Field(default="customer")
    billing_mode: str = Field(default="standard")
    risk_acknowledged: bool = False


class OrderCreateRequest(BaseModel):
    plan: str
    billing_country: str
    mode: ModeIn
    #: 客户交付的 session；仅内存处理，不持久化。
    session: Optional[str] = None
    #: 浏览器端支付组件产出的不透明标识（**不是卡号**）。
    payment_method_token: Optional[str] = None


class SubscriptionOut(BaseModel):
    active: bool
    expires_at: Optional[str] = None
    channel: Optional[str] = None


class OrderOut(BaseModel):
    id: str
    status: str
    plan: str
    billing_country: str
    mode: ModeIn
    checkout_url: Optional[str] = None
    subscription: Optional[SubscriptionOut] = None


class ErrorOut(BaseModel):
    code: str
    message: str
    detail: Optional[Dict[str, Any]] = None
