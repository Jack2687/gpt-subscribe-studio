"""适配器契约测试：能力声明、Fake 行为、上游 fail-fast（tasks.md T012/T013）。"""

from __future__ import annotations

import asyncio

import pytest

from dcp_account import FakeAccountAdapter, UpstreamAccountAdapter
from dcp_checkout import FakeCheckoutAdapter, UpstreamCheckoutAdapter
from dcp_contracts import (
    BillingMode,
    CheckoutRequest,
    ErrorCode,
    PaymentRequest,
    PaymentStatus,
    Plan,
)
from dcp_contracts.errors import DomainError
from dcp_payment import FakePaymentAdapter, UpstreamPaymentAdapter


ALL_ADAPTERS = [FakeCheckoutAdapter(), FakePaymentAdapter(), FakeAccountAdapter()]


@pytest.mark.parametrize("adapter", ALL_ADAPTERS)
def test_every_adapter_declares_capabilities(adapter) -> None:
    """每个 adapter 必须能回答来源 / 许可证 / 能力 / 失败模式（ADR 0001）。"""

    caps = adapter.capabilities()
    assert caps.source
    assert caps.license
    assert caps.supports
    assert caps.failure_modes


def test_no_license_upstreams_are_labelled() -> None:
    """无许可证上游必须被明确标注，避免误以为是开源。"""

    assert "NO-LICENSE" in UpstreamCheckoutAdapter().capabilities().license
    assert "NO-LICENSE" in UpstreamAccountAdapter().capabilities().license
    assert UpstreamPaymentAdapter().capabilities().license == "MIT"


def test_fake_checkout_standard_is_priced() -> None:
    fake = FakeCheckoutAdapter()
    req = CheckoutRequest(
        session="fake",
        plan=Plan.PLUS,
        billing_country="US",
        billing_mode=BillingMode.STANDARD,
    )
    res = asyncio.run(fake.create_checkout(req))
    assert res.currency == "USD"
    assert str(res.amount) == "20.00"
    assert res.checkout_url.endswith("/fake/1")


def test_fake_checkout_promo_is_zero() -> None:
    fake = FakeCheckoutAdapter()
    req = CheckoutRequest(
        session="fake",
        plan=Plan.PLUS,
        billing_country="PH",
        billing_mode=BillingMode.PROMO,
    )
    res = asyncio.run(fake.create_checkout(req))
    assert res.currency == "PHP"
    assert str(res.amount) == "0.00"


def test_fake_payment_scripted_3ds_then_success() -> None:
    fake = FakePaymentAdapter(
        scripted=[PaymentStatus.REQUIRES_ACTION, PaymentStatus.SUCCEEDED]
    )
    req = PaymentRequest(checkout_url="u", country="US", payment_method_token="pm_fake")
    first = asyncio.run(fake.pay(req))
    assert first.status is PaymentStatus.REQUIRES_ACTION
    assert first.next_action and first.next_action["type"] == "3ds_redirect"
    second = asyncio.run(fake.pay(req))
    assert second.status is PaymentStatus.SUCCEEDED
    assert len(fake.calls) == 2


def test_upstream_checkout_fails_fast_without_path(monkeypatch) -> None:
    monkeypatch.delenv("UPSTREAM_GPT_REGISTER_TOOL_PATH", raising=False)
    req = CheckoutRequest(
        session="s", plan=Plan.PLUS, billing_country="US", billing_mode=BillingMode.STANDARD
    )
    with pytest.raises(DomainError) as exc:
        asyncio.run(UpstreamCheckoutAdapter().create_checkout(req))
    assert exc.value.code is ErrorCode.CHECKOUT_UPSTREAM_ERROR


def test_upstream_payment_fails_fast_without_path(monkeypatch) -> None:
    monkeypatch.delenv("UPSTREAM_ZKKY_PATH", raising=False)
    req = PaymentRequest(checkout_url="u", country="US", payment_method_token="pm")
    with pytest.raises(DomainError) as exc:
        asyncio.run(UpstreamPaymentAdapter().pay(req))
    assert exc.value.code is ErrorCode.PAYMENT_UNKNOWN_STATE


def test_fake_account_reports_inactive_when_configured() -> None:
    fake = FakeAccountAdapter(active=False)
    info = asyncio.run(fake.subscription_status("s"))
    assert info.active is False
    assert info.expires_at is None
    assert fake.sessions_seen == ["s"]
