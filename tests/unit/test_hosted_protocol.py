"""Offline tests against a sanitized copy of the supplied successful HAR shape."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch

import pytest

from gss_contracts import PaymentRequest, PaymentStatus
from gss_core.chatgpt import ChatGPTClient
from gss_core.hosted import TeamHostedClient, HOSTED_API_VERSION, HOSTED_ELEMENTS_VERSION
from gss_payment.adapter import UpstreamPaymentAdapter, hosted_payment_result

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/team_hosted_success.json").read_text())
ADDRESS = {"country": "US", "state": "OR", "postal_code": "00000", "line1": "Fixture Street", "city": "Fixture City", "name": "Fixture User"}

def fields(name):
    return copy.deepcopy(FIXTURE[name]["record"]["response"]["fields"])

class HTTP:
    def __init__(self, due=115000):
        self.headers = {}
        self.calls = []
        self.due = due
    def post(self, url, data, **kwargs):
        body = {k: v[0] for k, v in parse_qs(data, keep_blank_values=True).items()}
        self.calls.append(("POST", url, body))
        if url.endswith("/init"):
            d = fields("init"); d["total_summary"] = {"due": 131100}
        elif url.endswith("/confirm"):
            d = fields("confirm")
        else:
            d = fields("init"); d["config_id"] = "fixture-config-updated"; d["total_summary"] = {"due": self.due}
        return SimpleNamespace(status_code=200, json=lambda: d)
    def get(self, url, params=None, **kwargs):
        self.calls.append(("GET", url, params or {}))
        d = fields("poll") if url.endswith("/poll") else fields("elements")
        return SimpleNamespace(status_code=200, json=lambda: d)
    def close(self): pass


def context(client):
    hosted = TeamHostedClient(client)
    hosted.current_timing = lambda _: "fixture-timing"
    return hosted.prepare(session_id="cs_test_fixture", key="pk_test_fixture",
        billing=ADDRESS, currency="EGP", browser_locale="en-US", browser_timezone="Asia/Tokyo")


@pytest.mark.parametrize("due", [115000, 0])
def test_hosted_prepare_order_versions_context_and_amount(due):
    client = ChatGPTClient(access_token="fixture"); http = HTTP(due); client._stripe_http = http
    c = context(client)
    # init, 3 address posts, elements GET, address refresh, 4 fingerprint registrations
    assert [x[0] for x in http.calls] == ["POST"] * 4 + ["GET"] + ["POST"] * 5
    assert http.calls[0][2] == {"key": "pk_test_fixture", "eid": "NA", "redirect_type": "url", "browser_locale": "en-US", "browser_timezone": "Asia/Tokyo"}
    assert http.calls[1][2]["tax_region[country]"] == "US"
    assert http.calls[3][2]["tax_region[state]"] == "OR"
    assert http.calls[2][2]["tax_id_collection[purchasing_as_business]"] == "false"
    elements = http.calls[4][2]
    assert elements["elements_init_source"] == "checkout"
    assert elements["referrer_host"] == "pay.openai.com"
    assert elements["_stripe_version"] == HOSTED_ELEMENTS_VERSION
    assert elements["deferred_intent[amount]"] == str(due)
    assert c["currency"] == "egp" and c["amount_minor"] == due
    assert c["checkout_config_id"] == "fixture-config-updated"
    assert c["checkout_config_id"] != fields("elements")["config_id"]
    assert c["passive_captcha"]["rqdata"] == fields("init")["rqdata"]
    # Device ids come from the live fingerprint endpoint or, on failure, local 42-char ids.
    assert all(isinstance(c[k], str) and c[k] for k in ("guid", "muid", "sid"))


def test_hosted_confirm_exact_fields_then_get_poll():
    client = ChatGPTClient(access_token="fixture"); http = HTTP(); client._stripe_http = http
    h = TeamHostedClient(client); c = context(client)
    h.confirm(c, "pm_fixture", passive_captcha_token="fixture-captcha", rv_timestamp="fixture-timing")
    body = http.calls[-1][2]
    expected = set(FIXTURE["confirm"]["record"]["request"]["fields"])
    assert set(body) == expected
    assert body["_stripe_version"] == HOSTED_API_VERSION
    # Confirm attribution matches the HAR hosted flow.
    assert body["client_attribution_metadata[merchant_integration_source]"] == "checkout"
    assert body["client_attribution_metadata[merchant_integration_version]"] == "hosted_checkout"
    assert body["client_attribution_metadata[payment_method_selection_flow]"] == "merchant_specified"

    assert body["client_attribution_metadata[checkout_config_id]"] == "fixture-config-updated"
    assert body["passive_captcha_token"] == "fixture-captcha"
    assert body["rv_timestamp"] == "fixture-timing"
    h.poll(session_id=c["session_id"], key=c["publishable_key"])
    assert http.calls[-1][0] == "GET" and http.calls[-1][2] == {"key": "pk_test_fixture"}


def test_recorded_top_level_success_without_payment_intent_is_success():
    result = hosted_payment_result(fields("poll"), "cs_test_fixture")
    assert result.status is PaymentStatus.SUCCEEDED


def test_recorded_challenge_is_stripe_verification_not_bank_3ds():
    d = fields("confirm")
    d["payment_intent"]["client_secret"] = "pi_fixture_secret_fixture"
    result = hosted_payment_result(d, "cs_test_fixture", "https://example.invalid/checkout")
    assert result.status is PaymentStatus.REQUIRES_ACTION
    assert result.next_action["challenge_type"] == "intent_confirmation_challenge"
    assert result.next_action["client_secret"] == "pi_fixture_secret_fixture"
    assert "3DS" not in result.message


def test_team_adapter_never_uses_chatgpt_approve_or_ctoken(monkeypatch):
    client = ChatGPTClient(access_token="fixture"); http = HTTP(); client._stripe_http = http
    c = context(client)
    monkeypatch.setattr("gss_payment.adapter.ChatGPTClient.from_raw_session", lambda *a, **kw: client)
    monkeypatch.setattr(client, "warmup", lambda **kw: pytest.fail("Team must not warmup ChatGPT"))
    monkeypatch.setattr(client, "approve_checkout", lambda **kw: pytest.fail("Team must not approve via ChatGPT"))
    monkeypatch.setattr(client, "create_confirmation_token", lambda **kw: pytest.fail("Team must not create ctoken"))
    req = PaymentRequest(checkout_url="https://example.invalid/checkout", country="EG", session="fixture",
        payment_method_token="pm_fixture", checkout_session_id="cs_test_fixture", publishable_key="pk_test_fixture",
        billing=ADDRESS, plan="team", team_context=c, passive_captcha_token="fixture-captcha", rv_timestamp="fixture-timing")
    result = asyncio.run(UpstreamPaymentAdapter().pay(req))
    assert result.status is PaymentStatus.REQUIRES_ACTION
    # Exactly one confirm; no mutation retries.
    assert len([x for x in http.calls if x[1].endswith("/confirm")]) == 1


def test_current_timing_reads_current_page_preload_not_captured_bundle_url():
    from gss_core.hosted_timing import decode_rv_timestamp
    calls = []
    script = 'const A="fixture-live-rv",B="fixture-live-sv";const x={rvTs:"2024-01-01 00:00:00 -0000",rv:A,sv:B};'
    class TimingHTTP:
        headers = {}
        def get(self, url, **kw):
            calls.append(url)
            text = '<link rel="preload" as="script" href="https://js.stripe.com/v3/fingerprinted/js/checkout-app-init-current.js"/>' if url.startswith('https://pay.openai.com/') else script
            return SimpleNamespace(status_code=200, text=text)
    client = ChatGPTClient(access_token="fixture"); client._stripe_http = TimingHTTP()
    value = TeamHostedClient(client).current_timing("cs_test_fixture")
    assert decode_rv_timestamp(value).rv == "fixture-live-rv"
    assert calls == ["https://pay.openai.com/c/pay/cs_test_fixture", "https://js.stripe.com/v3/fingerprinted/js/checkout-app-init-current.js"]


def test_current_timing_never_fetches_external_or_nonhttps_script():
    calls = []
    class TimingHTTP:
        headers = {}
        def get(self, url, **kw):
            calls.append(url)
            return SimpleNamespace(status_code=200, text='<link href="https://evil.invalid/v3/checkout-app-init.js"><script src="http://js.stripe.com/v3/checkout-app-init.js"></script>')
    client = ChatGPTClient(access_token="fixture"); client._stripe_http = TimingHTTP()
    assert TeamHostedClient(client).current_timing("cs_test_fixture") == ""
    assert calls == ["https://pay.openai.com/c/pay/cs_test_fixture"]


def test_quote_does_not_load_elements_captcha_or_confirm():
    client = ChatGPTClient(access_token="fixture"); http = HTTP(); client._stripe_http = http
    h = TeamHostedClient(client)
    result = h.quote(session_id="cs_test_fixture", key="pk_test_fixture", billing=None, currency="EGP")
    assert result["amount_minor"] == 131100
    assert len(http.calls) == 1 and http.calls[0][1].endswith("/init")


def test_prepare_publishes_quote_before_elements_failure():
    class ElementsFailure(HTTP):
        def get(self, url, **kwargs):
            error = TimeoutError("fixture transport timeout")
            error.code = 28
            raise error
    client = ChatGPTClient(access_token="fixture"); client._stripe_http = ElementsFailure()
    quotes = []
    from gss_contracts.errors import DomainError, ErrorCode
    with pytest.raises(DomainError) as error:
        TeamHostedClient(client).prepare(session_id="cs_test_fixture", key="pk_test_fixture", billing=ADDRESS,
                                        currency="EGP", on_quote=quotes.append)
    assert error.value.code is ErrorCode.CHECKOUT_UPSTREAM_ERROR
    assert "初始化支付组件" in error.value.message and "未提交付款确认" in error.value.message
    assert quotes[0]["amount_minor"] == 115000


@pytest.mark.parametrize("path,expected_code,fragment", [
    ("payment_pages/cs_test_fixture/init", "checkout_upstream_error", "初始化结账"),
    ("payment_pages/cs_test_fixture/confirm", "payment_unknown_state", "扣款结果待确认"),
])
def test_transport_failure_distinguishes_prepare_from_confirm(path, expected_code, fragment, caplog):
    from gss_contracts.errors import DomainError
    class Failed(HTTP):
        def post(self, url, **kwargs):
            e = TimeoutError("sensitive-detail-must-not-log")
            e.code = 28
            raise e
    client = ChatGPTClient(access_token="fixture"); client._stripe_http = Failed()
    with pytest.raises(DomainError) as caught:
        TeamHostedClient(client).post(path, {})
    assert caught.value.code.value == expected_code
    assert fragment in caught.value.message
    assert "code=28" in caplog.text and "sensitive-detail-must-not-log" not in caplog.text


def test_initialization_reconnects_once_without_changing_proxy_but_confirm_never_retries():
    from gss_contracts.errors import DomainError
    class Flaky(HTTP):
        attempts = 0
        def post(self, url, **kw):
            self.attempts += 1
            if self.attempts == 1: raise TimeoutError("fixture")
            return SimpleNamespace(status_code=200, json=lambda: {"status": "open"})
    client = ChatGPTClient(access_token="fixture"); http = Flaky(); client._stripe_http = http
    h = TeamHostedClient(client)
    assert h.post("payment_pages/cs_test_fixture/init", {})["status"] == "open"
    assert http.attempts == 2
    http.attempts = 0
    with pytest.raises(DomainError): h.post("payment_pages/cs_test_fixture/confirm", {})
    assert http.attempts == 1
