import base64
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from dcp_contracts.errors import DomainError, ErrorCode
from dcp_core.billing import address_for
from dcp_core.money import quote_from_payload
from dcp_core.chatgpt import (
    ChatGPTClient,
    checkout_confirm_blocked,
    checkout_confirm_blocked_advice,
    checkout_confirm_message,
    clamp_team_seats,
    hosted_checkout_url,
    intent_id_from_secret,
    jwt_account_id,
    payment_intent_from_confirm,
    setup_intent_from_payload,
    stripe_checkout_id,
)
from dcp_core.countries import country_codes, currency_for, is_supported
from dcp_core.proxies import (
    align_proxy_region,
    new_proxy_sid,
    proxy_exit_region,
    rewrite_proxy_exit,
    rotate_proxy_sid,
)
from dcp_core.sentinel import extract_attestation, extract_build, header_value, mint
from dcp_core.session_token import parse_session_bundle


def _jwt(account_id: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}).encode()
    ).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{payload}.x"


def test_jwt_account_id() -> None:
    assert jwt_account_id(_jwt("acct-123")) == "acct-123"
    assert jwt_account_id("not-a-jwt") == ""


def test_from_raw_session_uses_full_bundle() -> None:
    raw = json.dumps(
        {
            "accessToken": _jwt("acct-bundle"),
            "sessionToken": "sess-keep",
            "sessionId": "sid-keep",
            "cookies": {"oai-did": "did-keep", "cf_clearance": "cf-keep"},
        }
    )
    client = ChatGPTClient.from_raw_session(raw)
    assert client.account_id == "acct-bundle"
    assert client.session_token == "sess-keep"
    assert client.device_id == "did-keep"
    assert client.oai_session_id == "sid-keep"
    header = client._cookie_header()
    assert "sess-keep" in header
    assert "did-keep" in header
    assert "cf-keep" in header


def test_client_uses_jwt_account_without_hydrate() -> None:
    token = _jwt("acct-xyz")
    client = ChatGPTClient.from_raw_session(token)
    assert client.account_id == "acct-xyz"
    assert client.device_id
    assert client.oai_session_id


def test_unusual_activity_is_mapped() -> None:
    client = ChatGPTClient(access_token="tok")
    response = SimpleNamespace(
        status_code=400,
        text='{"detail":"Our systems have detected unusual activity. Please try again later."}',
    )
    with pytest.raises(DomainError) as exc:
        client._raise(ErrorCode.CHECKOUT_UPSTREAM_ERROR, response, "创建结账")
    assert exc.value.code is ErrorCode.CHECKOUT_UPSTREAM_ERROR
    assert "异常流量" in str(exc.value)


def test_session_bundle_reads_statsig_device() -> None:
    raw = json.dumps(
        {
            "accessToken": "tok_json",
            "sessionToken": "sess_json",
            "statsigContext": {"deviceId": "did-from-statsig", "country": "JP"},
        }
    )
    bundle = parse_session_bundle(raw)
    assert bundle.device_id == "did-from-statsig"


def test_session_bundle_reads_cookies() -> None:
    raw = json.dumps(
        {
            "accessToken": "tok_json",
            "sessionToken": "sess_json",
            "cookies": {"oai-did": "did-1"},
        }
    )
    bundle = parse_session_bundle(raw)
    assert bundle.access_token == "tok_json"
    assert bundle.session_token == "sess_json"
    assert bundle.device_id == "did-1"


def test_rotate_proxy_sid_changes_only_sid() -> None:
    original = "http://user-region-US-sid-AAAA1111:secret@us.example.com:3010"
    rotated = rotate_proxy_sid(original)
    assert rotated != original
    assert "us.example.com:3010" in rotated
    assert "region-US" in rotated
    assert "sid-AAAA1111" not in rotated


def test_rewrite_proxy_exit_changes_region_and_sid() -> None:
    original = "http://user-region-US-sid-AAAA1111:secret@us.example.com:3010"
    first = rewrite_proxy_exit(original, region="PH", sid=new_proxy_sid())
    second = rewrite_proxy_exit(original, region="CL", sid=new_proxy_sid())
    assert "region-PH" in first
    assert "region-CL" in second
    assert "region-US" not in first
    assert first != second
    assert "sid-AAAA1111" not in first
    assert "sid-AAAA1111" not in second


def test_supported_regions_include_requested_countries() -> None:
    for code, currency in (("US", "USD"), ("PH", "PHP"), ("CL", "CLP"), ("EG", "EGP")):
        assert is_supported(code)
        assert currency_for(code) == currency


def test_quote_from_payload_reads_major_and_minor_units() -> None:
    dollars, usd = quote_from_payload({"amount": "20.00", "currency": "USD"})
    assert dollars == Decimal("20.00") and usd == "USD"
    cents, usd_cents = quote_from_payload({"amount_total": 2000, "currency": "usd"})
    assert cents == Decimal("20.00") and usd_cents == "USD"
    yen, jpy = quote_from_payload({"invoice": {"amount_due": 2980, "currency": "jpy"}})
    assert yen == Decimal("2980") and jpy == "JPY"


def test_quote_from_chatgpt_checkout_state_skips_tax_line() -> None:
    amount, currency = quote_from_payload(
        {
            "currency": "JPY",
            "amount_total": None,
            "checkout_state": {
                "lineItems": [{"subtotal": {"minorUnitsAmount": 15273, "currency": "JPY"}}],
                "taxAmounts": [{"subtotal": {"minorUnitsAmount": 1527, "currency": "JPY"}}],
            },
        },
        "JPY",
    )
    assert amount == Decimal("15273") and currency == "JPY"
    taxed, taxed_currency = quote_from_payload({"amount_total": 15273, "currency": "jpy"})
    assert taxed == Decimal("15273") and taxed_currency == "JPY"


def test_checkout_confirm_blocked_is_detected() -> None:
    assert checkout_confirm_blocked({"status": "blocked"})
    assert checkout_confirm_blocked({"result": "blocked"})
    assert not checkout_confirm_blocked({"status": "success"})
    assert checkout_confirm_message({"status": "blocked", "error": {"code": "risk_blocked"}}) == "risk_blocked"
    us = checkout_confirm_blocked_advice("US")
    jp = checkout_confirm_blocked_advice("JP")
    assert "不能选美国" in us
    assert "日元" in jp
    assert "blocked" in us and "blocked" in jp


def test_payment_intent_from_chatgpt_confirm_success() -> None:
    intent_id, secret, return_url = payment_intent_from_confirm(
        {
            "status": "success",
            "type": "payment_intent",
            "client_secret": "pi_abc_secret_xyz",
            "confirm_return_url": "https://chatgpt.com/checkout/verify?stripe_session_id=oaics_1",
        }
    )
    assert intent_id == "pi_abc"
    assert secret == "pi_abc_secret_xyz"
    assert "checkout/verify" in return_url
    assert intent_id_from_secret("seti_only_secret_yyyy") == "seti_only"


def test_quote_from_payload_prefers_chatgpt_minor_fields() -> None:
    amount, currency = quote_from_payload(
        {
            "amount": "99.00",
            "checkout_amount_minor": 2000,
            "currency": "USD",
        }
    )
    assert amount == Decimal("20.00") and currency == "USD"
    php, php_code = quote_from_payload(
        {"total": {"taxInclusive": 114900, "currency": "php"}, "amount": "20.00"}
    )
    assert php == Decimal("1149.00") and php_code == "PHP"
    zero, usd = quote_from_payload({"checkout_amount_minor": 0, "currency": "USD"})
    assert zero == Decimal("0.00") and usd == "USD"


def test_setup_intent_from_payload_reads_nested_and_missing() -> None:
    setup_id, secret = setup_intent_from_payload(
        {
            "setup_intent": {
                "id": "seti_abc123",
                "client_secret": "seti_abc123_secret_zzzz",
            }
        }
    )
    assert setup_id == "seti_abc123"
    assert secret == "seti_abc123_secret_zzzz"
    from_secret = setup_intent_from_payload({"client_secret": "seti_only_secret_yyyy"})
    assert from_secret[0] == "seti_only"
    assert from_secret[1] == "seti_only_secret_yyyy"
    assert setup_intent_from_payload({"id": "pm_card"}) == ("", "")


def test_align_proxy_region_matches_billing_country() -> None:
    original = "http://user-region-US-sid-AAAA1111:secret@us.example.com:3010"
    aligned = align_proxy_region(original, "PH")
    assert aligned is not None
    assert proxy_exit_region(aligned) == "PH"
    assert "sid-AAAA1111" in aligned
    assert align_proxy_region(aligned, "PH") == aligned


def test_billing_address_matches_country() -> None:
    for code in country_codes():
        address = address_for(code)
        assert address["country"] == code
        assert address["name"]
        assert address["line1"]
        assert address["city"]
        assert address["postal_code"]
    us = address_for("US")
    assert us["state"]
    assert us["postal_code"].isdigit() and len(us["postal_code"]) == 5


def test_extract_attestation_and_build_from_html() -> None:
    html = (
        '<html data-build="ignored" data-seq="9758774">'
        '"sessionId":"11111111-2222-3333-4444-555555555555"'
        "prod-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        '"webDeploymentAttestation":"abc.def"'
        "</html>"
    )
    assert extract_attestation(html) == "abc.def"
    version, build, session_id = extract_build(html)
    assert version == "prod-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert build == "9758774"
    assert session_id == "11111111-2222-3333-4444-555555555555"


def test_header_value_strips_private_keys() -> None:
    raw = {"p": "pow", "c": "chal", "t": "turn", "id": "did", "flow": "chatgpt_checkout", "_so": {"so": "x"}}
    value = header_value(raw)
    assert '"p":"pow"' in value
    assert "_so" not in value


def test_mint_without_node_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_NODE", "/nonexistent-dcp-node")
    assert mint(flow="chatgpt_checkout", device_id="did", user_agent="ua") == {}


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, html: str) -> None:
        self.headers: dict = {}
        self.cookies: dict = {}
        self.posts: list = []
        self._html = html

    def get(self, url: str, **kwargs):
        if "stripe_client_bootstrap" in url:
            return _FakeResponse(payload={"publishable_key": "pk_test_liveish"})
        return _FakeResponse(text=self._html)

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, "headers": kwargs.get("headers") or {}, "json": kwargs.get("json")})
        return _FakeResponse(
            payload={
                "checkout_session_id": "cs_test_1",
                "processor_entity": "openai_llc",
                "publishable_key": "pk_test_liveish",
                "customer_session_client_secret": "cuss_test",
            }
        )


def test_create_checkout_sends_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    flows: list[str] = []

    def fake_mint(**kwargs):
        flows.append(str(kwargs.get("flow") or ""))
        return {"p": "pow", "c": "chal", "t": "turn", "id": kwargs.get("device_id"), "flow": kwargs.get("flow")}

    monkeypatch.setattr("dcp_core.chatgpt.mint", fake_mint)
    html = (
        'prod-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb '
        'data-seq="111" "webDeploymentAttestation":"sig.payload"'
    )
    client = ChatGPTClient.from_raw_session(_jwt("acct-sentinel"))
    client._http = _FakeHttp(html)
    created = client.create_checkout(plan="plus", country="US")
    assert flows == ["chatgpt_checkout"]
    assert created.checkout_session_id == "cs_test_1"
    assert created.customer_session_client_secret == "cuss_test"
    assert created.attestation == "sig.payload"
    headers = client._http.posts[0]["headers"]
    assert "openai-sentinel-token" in headers
    assert "oai-web-deployment-attestation" in headers
    assert '"flow":"chatgpt_checkout"' in headers["openai-sentinel-token"]
    body = client._http.posts[0]["json"]
    assert body["plan_name"] == "chatgptplusplan"
    assert body["checkout_source"] == "chatgpt_web_merged"
    assert body["purchase_attempt_id"]


def test_create_checkout_maps_pro_max_to_chatgptpro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dcp_core.chatgpt.mint",
        lambda **kwargs: {
            "p": "pow",
            "c": "chal",
            "t": "turn",
            "id": kwargs.get("device_id"),
            "flow": kwargs.get("flow"),
        },
    )
    client = ChatGPTClient.from_raw_session(_jwt("acct-sentinel"))
    client._http = _FakeHttp("")
    created = client.create_checkout(plan="pro_max", country="US")
    assert created.checkout_session_id == "cs_test_1"
    assert client._http.posts[0]["json"]["plan_name"] == "chatgptpro"
    assert client._http.posts[0]["json"]["billing_details"]["country"] == "US"


def test_stripe_automatic_payment_methods_conflict_is_mapped() -> None:
    payload = {
        "error": {
            "message": (
                "Payment details were collected through Stripe Elements using automatic payment methods "
                "and cannot be confirmed through the API configured with payment_method_types or "
                "allowed_payment_method_types."
            )
        }
    }
    with pytest.raises(DomainError) as exc:
        from dcp_core.chatgpt import _raise_stripe

        _raise_stripe(payload, 400)
    assert "采集模式和确认接口不一致" in str(exc.value)
    assert "automatic payment methods" not in str(exc.value)


def test_chatgpt_http_500_is_mapped() -> None:
    client = ChatGPTClient(access_token="tok")
    response = SimpleNamespace(status_code=500, text='{"detail":"Internal Server Error"}')
    with pytest.raises(DomainError) as exc:
        client._raise(ErrorCode.CHECKOUT_UPSTREAM_ERROR, response, "创建结账")
    assert "暂时返回 500" in str(exc.value)
    assert "Internal Server Error" not in str(exc.value)


def test_team_seats_and_hosted_url() -> None:
    assert clamp_team_seats(8) == 8
    with pytest.raises(ValueError, match="最少 2"):
        clamp_team_seats(1)
    assert stripe_checkout_id("https://checkout.stripe.com/c/pay/cs_live_abc123") == "cs_live_abc123"
    url = hosted_checkout_url("", "cs_live_abc123")
    assert url.startswith("https://pay.openai.com/c/pay/cs_live_abc123#")


def test_create_checkout_maps_team_seats_and_promo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dcp_core.chatgpt.mint",
        lambda **kwargs: {
            "p": "pow",
            "c": "chal",
            "t": "turn",
            "id": kwargs.get("device_id"),
            "flow": kwargs.get("flow"),
        },
    )
    client = ChatGPTClient.from_raw_session(_jwt("acct-sentinel"))
    client._http = _FakeHttp("")
    created = client.create_checkout(
        plan="team",
        country="JP",
        promo_code="TEAM50",
        workspace_name="Desk",
        seat_quantity=8,
        price_interval="month",
    )
    body = client._http.posts[0]["json"]
    assert body["plan_name"] == "chatgptteamplan"
    assert body["checkout_ui_mode"] == "redirect"
    assert body["team_plan_data"]["seat_quantity"] == 8
    assert body["team_plan_data"]["workspace_name"] == "Desk"
    assert body["promo_code"] == "TEAM50"
    assert body["billing_details"]["currency"] == "JPY"
    assert created.checkout_kind == "hosted"
    assert "pay.openai.com/c/pay/cs_test_1" in created.checkout_url


def test_create_checkout_maps_go_lite_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "dcp_core.chatgpt.mint",
        lambda **kwargs: {
            "p": "pow",
            "c": "chal",
            "t": "turn",
            "id": kwargs.get("device_id"),
            "flow": kwargs.get("flow"),
        },
    )
    client = ChatGPTClient.from_raw_session(_jwt("acct-sentinel"))
    client._http = _FakeHttp("")
    created = client.create_checkout(plan="pro_lite", country="JP")
    assert created.checkout_session_id == "cs_test_1"
    assert client._http.posts[0]["json"]["plan_name"] == "chatgptprolite"
    assert client._http.posts[0]["json"]["billing_details"]["currency"] == "JPY"


def test_create_checkout_fails_closed_without_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dcp_core.chatgpt.mint", lambda **kwargs: {})
    client = ChatGPTClient.from_raw_session(_jwt("acct-sentinel"))
    client._http = _FakeHttp("")
    with pytest.raises(DomainError) as exc:
        client.create_checkout(plan="plus", country="US")
    assert "风控令牌" in str(exc.value)
