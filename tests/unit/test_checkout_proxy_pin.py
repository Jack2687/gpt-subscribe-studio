"""Team selects a live proxy before checkout and preserves it privately."""
import asyncio
from types import SimpleNamespace

import pytest

from gss_checkout.adapter import UpstreamCheckoutAdapter, _probe_stripe_proxy
from gss_contracts import CheckoutRequest, BillingMode, Plan
from gss_contracts.errors import DomainError, ErrorCode


def request(plan=Plan.TEAM):
    return CheckoutRequest(session="fixture", plan=plan, billing_country="EG", billing_mode=BillingMode.STANDARD,
                           proxy="http://fixture.invalid:3010", seat_quantity=2)


def created():
    return SimpleNamespace(checkout_url="https://example.invalid/fixture", currency="EGP", amount=None,
                           checkout_session_id="cs_test_fixture", publishable_key="pk_test_fixture",
                           customer_session_client_secret=None, checkout_kind="hosted", confirm_return_url="")


def setup(monkeypatch):
    monkeypatch.setattr("gss_checkout.adapter.align_proxy_region", lambda proxy, country: proxy)
    values = iter(("http://new1.invalid:3010", "http://new2.invalid:3010"))
    monkeypatch.setattr("gss_checkout.adapter.rotate_proxy_sid", lambda proxy: next(values))


def test_dead_candidate_is_replaced_before_create_and_effective_proxy_is_preserved(monkeypatch):
    setup(monkeypatch)
    checks = []
    def probe(proxy, **kw): checks.append(proxy); return len(checks) > 1
    monkeypatch.setattr("gss_checkout.adapter._probe_stripe_proxy", probe)
    adapter = UpstreamCheckoutAdapter(); calls = []
    monkeypatch.setattr(adapter, "_create", lambda req, proxy: calls.append(proxy) or created())
    result = asyncio.run(adapter.create_checkout(request()))
    assert calls == ["http://new1.invalid:3010"]
    assert result.effective_proxy == calls[0]
    assert "effective_proxy" not in repr(result)
    assert checks == ["http://fixture.invalid:3010", "http://new1.invalid:3010"]


def test_unusual_activity_rotation_returns_actual_used_proxy(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr("gss_checkout.adapter._probe_stripe_proxy", lambda *a, **kw: True)
    calls = []
    def create(req, proxy):
        calls.append(proxy)
        if len(calls) == 1: raise DomainError(ErrorCode.CHECKOUT_UPSTREAM_ERROR, "异常流量")
        return created()
    adapter = UpstreamCheckoutAdapter(); monkeypatch.setattr(adapter, "_create", create)
    result = asyncio.run(adapter.create_checkout(request()))
    assert result.effective_proxy == calls[-1] == "http://new1.invalid:3010"


def test_all_failed_proxies_do_not_create_checkout_or_fallback_to_direct(monkeypatch):
    setup(monkeypatch)
    seen = []
    monkeypatch.setattr("gss_checkout.adapter._probe_stripe_proxy", lambda proxy, **kw: seen.append(proxy) or False)
    adapter = UpstreamCheckoutAdapter(); monkeypatch.setattr(adapter, "_create", lambda *a: pytest.fail("No checkout on failed proxies"))
    with pytest.raises(DomainError, match="未创建结账/未付款"):
        asyncio.run(adapter.create_checkout(request()))
    assert seen == ["http://fixture.invalid:3010", "http://new1.invalid:3010", "http://new2.invalid:3010"]


def test_plus_path_does_not_add_team_preflight(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr("gss_checkout.adapter._probe_stripe_proxy", lambda *a, **kw: pytest.fail("Plus preflight changed"))
    adapter = UpstreamCheckoutAdapter(); monkeypatch.setattr(adapter, "_create", lambda *a: created())
    result = asyncio.run(adapter.create_checkout(request(Plan.PLUS)))
    assert result.effective_proxy == "http://fixture.invalid:3010"


@pytest.mark.parametrize("http_status,expected", [(401,True),(404,True),(407,False),(503,False)])
def test_preflight_uses_proxy_and_accepts_unauthenticated_stripe_response(monkeypatch,http_status,expected):
    calls=[]
    class HTTP:
        def get(self,url,**kw): calls.append((url,kw)); return SimpleNamespace(status_code=http_status)
        def close(self): calls.append("closed")
    def session(**kw):
        assert kw["proxy"] == "http://fixture.invalid:3010"
        assert kw["timeout"] == 8
        return HTTP()
    monkeypatch.setattr("gss_core.chatgpt._new_session",session)
    assert _probe_stripe_proxy("http://fixture.invalid:3010") is expected
    assert calls[-1] == "closed"
