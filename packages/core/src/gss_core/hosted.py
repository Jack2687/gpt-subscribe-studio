"""Team Hosted Checkout protocol. No ChatGPT Custom Checkout beta fields."""
from __future__ import annotations

import time
import uuid
import html
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urljoin

from gss_contracts.errors import DomainError, ErrorCode

HOSTED_API_VERSION = "2020-08-27;custom_checkout_beta=v1"
HOSTED_ELEMENTS_VERSION = "2026-03-25.dahlia"


def device_id() -> str:
    return str(uuid.uuid4()) + uuid.uuid4().hex[:6]


class TeamHostedClient:
    def __init__(self, client):
        self.client = client
        self.http = client.stripe_http
        self.http.headers.update({"Origin": "https://pay.openai.com", "Referer": "https://pay.openai.com/"})

    def post(self, path: str, fields: dict[str, Any]) -> dict:
        # Confirm is a mutation: never replay it to remove unsupported fields.
        try:
            response = self.http.post("https://api.stripe.com/v1/" + path,
                                      data=urlencode(fields), timeout=self.client.timeout)
        except Exception as exc:
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "Stripe 请求中断，请查询支付状态，避免重复确认") from exc
        return self.response(response)

    def get(self, path: str, params: dict[str, Any]) -> dict:
        try:
            response = self.http.get("https://api.stripe.com/v1/" + path,
                                     params=params, timeout=self.client.timeout)
        except Exception as exc:
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "Stripe 状态查询暂时中断，请稍后重查") from exc
        return self.response(response)

    @staticmethod
    def response(response) -> dict:
        from .chatgpt import _json, _raise_stripe
        payload = _json(response)
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            _raise_stripe(payload, status)
        return payload

    def current_timing(self, session_id: str) -> str:
        """Read the live Hosted page and its declared Stripe init bundle; never replay HAR URLs."""
        from .hosted_timing import rv_timestamp_from_script
        timeout = min(float(self.client.timeout), 15)
        page_url = f"https://pay.openai.com/c/pay/{session_id}"
        try:
            page = self.http.get(page_url, timeout=timeout, allow_redirects=False)
            if int(getattr(page, "status_code", 0)) != 200:
                return ""
            text = str(getattr(page, "text", ""))
            if len(text) > 4_000_000:
                return ""
            value = rv_timestamp_from_script(text)
            if value:
                return value
            urls = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', text)
            for raw in urls:
                url = html.unescape(urljoin(page_url, raw))
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname != "js.stripe.com" or parsed.username or parsed.password:
                    continue
                if not parsed.path.startswith("/v3/") or "checkout-app-init" not in parsed.path or not parsed.path.endswith(".js"):
                    continue
                script = self.http.get(url, timeout=timeout, allow_redirects=False)
                if int(getattr(script, "status_code", 0)) != 200:
                    return ""
                source = str(getattr(script, "text", ""))
                return (rv_timestamp_from_script(source) or "") if len(source) <= 8_000_000 else ""
        except Exception:
            return ""
        return ""

    def prepare(self, *, session_id: str, key: str, billing: dict[str, str],
                currency: str, browser_locale: str = "en-US", browser_timezone: str = "UTC") -> dict:
        from .chatgpt import expected_amount_minor
        if not re.fullmatch(r"cs_(?:live|test)_[A-Za-z0-9_]+", session_id) or not key.startswith("pk_"):
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "Hosted Checkout 会话或公钥缺失")
        prefix = f"payment_pages/{session_id}"
        init = self.post(prefix + "/init", {"key": key, "eid": "NA", "redirect_type": "url",
                                          "browser_locale": browser_locale, "browser_timezone": browser_timezone})
        eid = str(init.get("eid") or "NA")
        # Match the Hosted page: select billing country, personal purchase, then full address.
        self.post(prefix, {"key": key, "eid": eid, "tax_region[country]": billing["country"]})
        self.post(prefix, {"key": key, "eid": eid, "tax_id_collection[purchasing_as_business]": "false"})
        address = {"key": key, "eid": eid}
        for name in ("country", "state", "postal_code", "line1", "city"):
            value = str(billing.get(name) or "").strip()
            if value:
                address[f"tax_region[{name}]"] = value
        tax = self.post(prefix, address)
        amount = expected_amount_minor(tax)
        if amount is None:
            amount = expected_amount_minor(init)
        if amount is None:
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "Team Hosted Checkout 缺少应付金额")
        code = str(init.get("currency") or currency).lower()
        js_id = str(uuid.uuid4())
        params = {"key": key, "type": "deferred_intent", "checkout_session_id": session_id,
                  "hosted_surface": "checkout", "elements_init_source": "checkout",
                  "referrer_host": "pay.openai.com", "stripe_js_id": js_id,
                  "locale": browser_locale, "browser_timezone": browser_timezone,
                  "deferred_intent[mode]": "subscription", "deferred_intent[amount]": str(amount),
                  "deferred_intent[currency]": code, "deferred_intent[setup_future_usage]": "off_session",
                  "deferred_intent[payment_method_types][0]": "card",
                  "client_betas[0]": "google_pay_beta_1",
                  "client_betas[1]": "disable_deferred_intent_client_validation_beta_1",
                  "client_betas[2]": "blocked_card_brands_beta_2",
                  "_stripe_version": HOSTED_ELEMENTS_VERSION}
        elements = self.get("elements/sessions", params)
        captcha = elements.get("passive_captcha") or {}
        site_key = tax.get("site_key") or init.get("site_key") or captcha.get("site_key")
        rqdata = tax.get("rqdata") or init.get("rqdata") or captcha.get("rqdata")
        captcha_settings = {"site_key": site_key, "rqdata": rqdata}
        if captcha.get("token_timeout_seconds"):
            captcha_settings["token_timeout_seconds"] = captcha["token_timeout_seconds"]
        timing = self.current_timing(session_id)
        if not timing:
            raise DomainError(ErrorCode.CHECKOUT_UPSTREAM_ERROR, "当前官方结账脚本的会话字段提取失败，请打开官方长链完成付款")
        return {"context_id": str(uuid.uuid4()), "session_id": session_id, "publishable_key": key,
                "eid": eid, "amount_minor": amount, "currency": code,
                "checkout_config_id": str(tax.get("config_id") or init.get("config_id") or ""),
                "elements_session_id": str(elements.get("session_id") or ""),
                "client_session_id": js_id, "guid": device_id(), "muid": device_id(), "sid": device_id(),
                "billing": dict(billing), "prepared_at": time.time(),
                "passive_captcha": captcha_settings,
                "customer_email": str(billing.get("email") or init.get("customer_email") or ""),
                "rv_timestamp": timing}

    def confirm(self, context: dict, payment_method: str, *, passive_captcha_token: str = "",
                rv_timestamp: str = "") -> dict:
        if not payment_method.startswith("pm_"):
            raise DomainError(ErrorCode.PAYMENT_DECLINED, "Team 需要浏览器返回的 pm_ 标识")
        body = {"key": context["publishable_key"], "_stripe_version": HOSTED_API_VERSION,
                "eid": context["eid"], "payment_method": payment_method,
                "expected_amount": str(context["amount_minor"]),
                "consent[terms_of_service]": "accepted", "expected_payment_method_type": "card",
                "guid": context["guid"], "muid": context["muid"], "sid": context["sid"],
                "client_attribution_metadata[client_session_id]": context["client_session_id"],
                "client_attribution_metadata[checkout_session_id]": context["session_id"],
                "client_attribution_metadata[merchant_integration_source]": "checkout",
                "client_attribution_metadata[merchant_integration_version]": "hosted_checkout",
                "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
                "client_attribution_metadata[checkout_config_id]": context["checkout_config_id"],
                "link_brand": "link", "passive_captcha_ekey": ""}
        if passive_captcha_token:
            body["passive_captcha_token"] = passive_captcha_token
        timing = str(context.get("rv_timestamp") or rv_timestamp or "")
        if timing:
            body["rv_timestamp"] = timing
        return self.post(f"payment_pages/{context['session_id']}/confirm", body)

    def poll(self, *, session_id: str, key: str) -> dict:
        return self.get(f"payment_pages/{session_id}/poll", {"key": key})
