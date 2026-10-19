"""Server-side card tokenization through the Elements surface, offline."""
import json
from types import SimpleNamespace

import pytest

from gss_contracts.errors import DomainError, ErrorCode
from gss_core import tokenize as tokenize_module
from gss_core.tokenize import normalize_card, tokenize_card

BILLING = {"name": "Fixture User", "line1": "1 Fixture Street", "city": "Portland",
           "state": "OR", "postal_code": "97205", "country": "US", "email": "fixture@example.invalid"}


def card(number="4242424242424242", cvc="123", month="12", year="2030"):  # release-check: ignore
    # Synthetic runtime fixture; not a stored payment credential.
    return {"number": number, "cvc": cvc, "exp_month": month, "exp_year": year}


class HTTP:
    def __init__(self, status=200, payload=None, raises=False):
        self.status = status
        self.payload = payload if payload is not None else {"id": "pm_fixture", "card": {"brand": "visa", "last4": "4242", "funding": "credit"}}
        self.raises = raises
        self.calls = []

    def post(self, url, data=None, headers=None, timeout=None, **kw):
        self.calls.append({"url": url, "data": dict(data or {}), "headers": dict(headers or {})})
        if self.raises:
            raise TimeoutError("fixture transport timeout")
        return SimpleNamespace(status_code=self.status, json=lambda: self.payload)


def test_tokenize_sends_elements_attribution_from_js_stripe_origin():
    http = HTTP()
    pm = tokenize_card(http, card=card(), billing=BILLING, publishable_key="pk_live_fixture",
                       checkout_session_id="cs_live_fixture",
                       device={"guid": "g1", "muid": "m1", "sid": "s1", "client_session_id": "c1"})
    assert pm == "pm_fixture"
    call = http.calls[0]
    assert call["url"] == "https://api.stripe.com/v1/payment_methods"
    assert call["headers"]["Origin"] == "https://js.stripe.com"
    data = call["data"]
    assert data["card[number]"] == "4242424242424242"  # release-check: ignore
    assert data["client_attribution_metadata[merchant_integration_source]"] == "elements"
    assert data["client_attribution_metadata[merchant_integration_subtype]"] == "payment-element"
    assert data["client_attribution_metadata[payment_method_selection_flow]"] == "automatic"
    assert data["client_attribution_metadata[checkout_session_id]"] == "cs_live_fixture"
    assert data["guid"] == "g1" and data["muid"] == "m1" and data["sid"] == "s1"
    assert data["_stripe_version"] == "2025-03-31.basil"
    assert "radar_options[hcaptcha_token]" not in data


def test_captcha_token_is_forwarded_when_present():
    http = HTTP()
    tokenize_card(http, card=card(), billing=BILLING, publishable_key="pk_live_fixture",
                  checkout_session_id="cs_live_fixture", captcha_token="chal_fixture")
    assert http.calls[0]["data"]["radar_options[hcaptcha_token]"] == "chal_fixture"


def test_card_error_is_surfaced_without_card_secrets(caplog):
    # Public Stripe decline-test PAN, not a real card.
    number, cvc = "4000000000000002", "987"  # release-check: ignore
    http = HTTP(status=400, payload={"error": {
        "type": "card_error", "code": "card_declined", "decline_code": "generic_decline",
        "message": f"Card {number} cvc {cvc} declined"}})
    with pytest.raises(DomainError) as caught:
        tokenize_card(http, card=card(number=number, cvc=cvc), billing=BILLING,
                      publishable_key="pk_live_fixture", checkout_session_id="cs_live_fixture")
    assert caught.value.code is ErrorCode.PAYMENT_DECLINED
    assert "card_declined" in caught.value.message
    assert number not in caught.value.message and cvc not in caught.value.message


def test_live_mode_test_card_error_is_reported_verbatim():
    message = "Your request was in live mode, but used a known test card."
    http = HTTP(status=400, payload={"error": {"type": "card_error", "code": "card_declined",
                                               "decline_code": "live_mode_test_card", "message": message}})
    with pytest.raises(DomainError) as caught:
        tokenize_card(http, card=card(), billing=BILLING, publishable_key="pk_live_fixture",
                      checkout_session_id="cs_live_fixture")
    assert "live_mode_test_card" in caught.value.message


def test_surface_rejection_is_not_reported_as_card_failure():
    message = "This integration surface is unsupported for publishable key tokenization."
    http = HTTP(status=400, payload={"error": {"type": "invalid_request_error", "message": message}})
    with pytest.raises(DomainError) as caught:
        tokenize_card(http, card=card(), billing=BILLING, publishable_key="pk_live_fixture",
                      checkout_session_id="cs_live_fixture")
    assert "unsupported for publishable key" in caught.value.message


def test_missing_publishable_key_or_session_is_rejected_before_network():
    http = HTTP()
    for kw in ({"publishable_key": "", "checkout_session_id": "cs_live_x"},
               {"publishable_key": "pk_live_x", "checkout_session_id": "oaics_x"}):
        with pytest.raises(DomainError):
            tokenize_card(http, card=card(), billing=BILLING, **kw)
    assert http.calls == []


def test_transport_failure_is_unknown_state_not_declined():
    with pytest.raises(DomainError) as caught:
        tokenize_card(HTTP(raises=True), card=card(), billing=BILLING,
                      publishable_key="pk_live_fixture", checkout_session_id="cs_live_fixture")
    assert caught.value.code is ErrorCode.PAYMENT_UNKNOWN_STATE


@pytest.mark.parametrize("bad", [
    {"number": "12", "cvc": "123", "exp_month": "12", "exp_year": "2030"},
    {"number": "4242424242424242", "cvc": "1", "exp_month": "12", "exp_year": "2030"},  # release-check: ignore
    {"number": "4242424242424242", "cvc": "123", "exp_month": "13", "exp_year": "2030"},  # release-check: ignore
    {"number": "4242424242424242", "cvc": "123", "exp_month": "12", "exp_year": "30x"},  # release-check: ignore
])
def test_card_validation_rejects_malformed_input(bad):
    with pytest.raises(DomainError):
        normalize_card(bad)


def test_two_digit_year_is_expanded():
    assert normalize_card(card(year="30"))["exp_year"] == "2030"


def test_fingerprint_registration_falls_back_locally_on_failure():
    from gss_core.fingerprint import register_device
    ids = register_device(HTTP(raises=True))
    assert all(isinstance(ids[k], str) and len(ids[k]) >= 32 for k in ("guid", "muid", "sid"))


def test_fingerprint_registration_uses_server_assigned_ids():
    from gss_core.fingerprint import register_device

    class FP:
        def __init__(self):
            self.calls = 0
        def post(self, url, data=None, headers=None, timeout=None):
            self.calls += 1
            body = {"guid": "server-guid", "muid": "server-muid", "sid": "server-sid"}
            return SimpleNamespace(status_code=200, json=lambda: body)

    fp = FP()
    ids = register_device(fp)
    assert ids == {"guid": "server-guid", "muid": "server-muid", "sid": "server-sid"}
    assert fp.calls == 4
