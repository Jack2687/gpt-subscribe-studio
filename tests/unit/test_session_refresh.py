"""session 刷新对齐：用账单国出口请求 /api/auth/session，换取与本次 IP 同批次的凭证。

结账地区由出口代理决定，session 本身不绑定国家；刷新是风控缓解措施，
必须软失败（不阻断结账/支付）。
"""

from __future__ import annotations

import asyncio

import pytest

from gss_checkout import UpstreamCheckoutAdapter
from gss_contracts import BillingMode, CheckoutRequest, PaymentRequest, Plan
from gss_contracts.errors import DomainError, ErrorCode
from gss_core.chatgpt import ChatGPTClient
from gss_payment.adapter import UpstreamPaymentAdapter

from test_chatgpt_protocol import _jwt


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _SessionHttp:
    """可编程的 /api/auth/session 桩。"""

    def __init__(self, *, payload: dict | None = None, status: int = 200, raises: bool = False) -> None:
        self.headers: dict = {}
        self.cookies: dict = {"oai-sc": "sc-from-refresh"}
        self.posts: list = []
        self.gets: list = []
        self._payload = payload or {}
        self._status = status
        self._raises = raises

    def get(self, url: str, **kwargs):
        if self._raises:
            raise RuntimeError("network down")
        self.gets.append(url)
        return _FakeResponse(status_code=self._status, payload=self._payload)

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url})
        return _FakeResponse(payload={})


def _client_with_session_token() -> ChatGPTClient:
    client = ChatGPTClient.from_raw_session(_jwt("acct-refresh"))
    client.session_token = "sess-token"
    return client


def test_refresh_session_updates_token_and_cookies() -> None:
    client = _client_with_session_token()
    client._http = _SessionHttp(payload={"accessToken": _jwt("acct-refreshed")})

    assert client.refresh_session() is True
    assert client.access_token == _jwt("acct-refreshed")
    assert client.extra_cookies["oai-sc"] == "sc-from-refresh"
    assert any("/api/auth/session" in url for url in client._http.gets)


def test_refresh_session_soft_fails_on_network_error() -> None:
    client = _client_with_session_token()
    original = client.access_token
    client._http = _SessionHttp(raises=True)

    assert client.refresh_session() is False
    assert client.access_token == original


def test_refresh_session_soft_fails_on_upstream_error() -> None:
    client = _client_with_session_token()
    original = client.access_token
    client._http = _SessionHttp(status=500)

    assert client.refresh_session() is False
    assert client.access_token == original


def test_refresh_session_ignores_expired_session_token() -> None:
    """session-token 失效时上游返回 200 + 空 accessToken，不能拿空 token 覆盖。"""

    client = _client_with_session_token()
    original = client.access_token
    client._http = _SessionHttp(payload={})

    assert client.refresh_session() is False
    assert client.access_token == original


def test_refresh_session_without_session_token_is_noop() -> None:
    client = ChatGPTClient.from_raw_session(_jwt("acct-refresh"))
    client._http = _SessionHttp(payload={"accessToken": _jwt("acct-other")})

    assert client.refresh_session() is False
    assert client.access_token == _jwt("acct-refresh")
    assert client._http.gets == []


class _StubCheckoutClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def refresh_session(self) -> bool:
        self.calls.append("refresh")
        return True

    def create_checkout(self, **kwargs):
        self.calls.append("create")
        from gss_core.chatgpt import CheckoutSession

        return CheckoutSession(
            checkout_session_id="cs_test_1",
            publishable_key="pk_live_test",
            account_id="acct-stub",
            checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test_1",
            currency="USD",
        )

    def close(self) -> None:
        self.calls.append("close")


def test_checkout_adapter_refreshes_session_before_create(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubCheckoutClient()

    class _Factory:
        @staticmethod
        def from_raw_session(raw: str, proxy=None) -> _StubCheckoutClient:
            return stub

    monkeypatch.setattr("gss_checkout.adapter.ChatGPTClient", _Factory)

    result = asyncio.run(
        UpstreamCheckoutAdapter().create_checkout(
            CheckoutRequest(
                session="sess",
                plan=Plan.PLUS,
                billing_country="US",
                billing_mode=BillingMode.STANDARD,
            )
        )
    )

    assert result.checkout_session_id == "cs_test_1"
    # 刷新必须发生在创建结账之前；刷新失败也不阻断结账。
    assert stub.calls.index("refresh") < stub.calls.index("create")


class _StubPaymentClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def refresh_session(self) -> bool:
        self.calls.append("refresh")
        return True

    def warmup(self, *, page_url: str = "") -> None:
        self.calls.append("warmup")

    def confirm_checkout(self, **kwargs):
        self.calls.append("confirm")
        raise DomainError(ErrorCode.PAYMENT_DECLINED, "declined on purpose")


def test_payment_adapter_refreshes_session_before_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubPaymentClient()

    class _Factory:
        @staticmethod
        def from_raw_session(raw: str, proxy=None) -> _StubPaymentClient:
            return stub

    monkeypatch.setattr("gss_payment.adapter.ChatGPTClient", _Factory)

    with pytest.raises(DomainError):
        asyncio.run(
            UpstreamPaymentAdapter().pay(
                PaymentRequest(
                    checkout_url="https://chatgpt.com/checkout/openai_llc/cs_test_1",
                    country="US",
                    payment_method_token="ctoken_1",
                    session="sess",
                    checkout_session_id="cs_test_1",
                    publishable_key="pk_live_test",
                    plan="plus",
                )
            )
        )

    assert stub.calls.index("refresh") < stub.calls.index("warmup") < stub.calls.index("confirm")
