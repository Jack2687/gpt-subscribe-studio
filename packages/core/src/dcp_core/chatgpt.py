"""本项目自己的 ChatGPT / Stripe 客户端。建单协议对齐公开的直卡提链实现。"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from dcp_contracts.errors import DomainError, ErrorCode
from dcp_core.billing import address_for
from dcp_core.countries import currency_for, locale_for, timezone_for
from dcp_core.money import quote_from_payload
from dcp_core.redaction import redact_sensitive
from dcp_core.sentinel import extract_attestation, extract_build, header_value, mint, so_header_value
from dcp_core.session_token import SessionBundle, parse_session_bundle

APP_BASE = "https://chatgpt.com"
STRIPE_BASE = "https://api.stripe.com"
_IMPERSONATE = "chrome136"
_CLIENT_VERSION = "prod-db390ebea64862bf1899c420a4c736e0cf639747"
_CLIENT_BUILD = "7904904"
_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)
_SEC_CH_UA = '"Google Chrome";v="136", "Not.A/Brand";v="8", "Chromium";v="136"'

STRIPE_API_VERSION = "2025-03-31.basil"
STRIPE_CHECKOUT_API_VERSION = (
    "2025-03-31.basil; checkout_server_update_beta=v1; "
    "checkout_manual_approval_preview=v1"
)
logger = logging.getLogger("dcp.chatgpt")
_PLAN_NAME = {
    "plus": "chatgptplusplan",
    "go": "chatgptgoplan",
    "pro_lite": "chatgptprolite",
    "pro": "chatgptpro",
    "pro_max": "chatgptpromax",
    "team": "chatgptteamplan",
}
_PLAN_TYPE = {
    "plus": "plus",
    "go": "go",
    "pro_lite": "prolite",
    "pro": "pro",
    "pro_max": "promax",
    "team": "team",
    "chatgptplusplan": "plus",
    "chatgptgoplan": "go",
    "chatgptprolite": "prolite",
    "chatgptpro": "pro",
    "chatgptpromax": "promax",
    "chatgptteamplan": "team",
}

# Stripe Checkout 托管页片段（公开 UI 状态，不是密钥）。Team 长链与 153 同源协议。
_HOSTED_CHECKOUT_FRAGMENT = (
    "#fidnandhYHdWcXxpYCc%2FJ2FgY2RwaXEnKSdpamZkaWAnPyd%2FbScpJ3ZwZ3Zmd2x1cWxqa1Brb"
    "HRwYGtgdnZAa2RnaWBhJz9jZGl2YCknYnBkZmRoamlgU2R3bGRrcSc%2FJ2Zqa3F3amknKSdkdWxO"
    "YHwnPyd1blppbHNgWjA0TUp3VnJGM200a31Cakw2aVFEYldvXFN3fzFhUDZjU0pkZ3xGZk5XNnVnQ"
    "E9icEZTRGl0Rn1hfUZQc2pXbTRdUnJXZGZTbGpzUDZuSU5zdW5vbTJMdG5SNTVsXVR2b2o2aycpJ2"
    "N3amhWYHdzYHcnP3F3cGApJ2dkZm5id2pwa2FGamlqdyc%2FJyZjY2NjY2MnKSdpZHxqcHFRfHVgJ"
    "z8ndmxrYmlgWmxxYGgnKSdga2RnaWBVaWRmYG1qaWFgd3YnP3F3cGB4JSUl"
)
_CS_ID = re.compile(r"cs_(?:live|test)_[A-Za-z0-9]+")
_OAICS_ID = re.compile(r"oaics_[A-Za-z0-9]+")


def clamp_team_seats(value: Any) -> int:
    try:
        seats = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Team 席位必须是整数") from exc
    if seats < 2:
        raise ValueError("Team 最少 2 个席位")
    if seats > 999:
        raise ValueError("Team 最多 999 个席位")
    return seats


def _first_id(pattern: re.Pattern[str], *blobs: Any) -> str:
    for blob in blobs:
        if isinstance(blob, dict):
            for value in _walk(blob):
                if isinstance(value, str):
                    match = pattern.search(value)
                    if match:
                        return match.group(0)
        elif isinstance(blob, str):
            match = pattern.search(blob)
            if match:
                return match.group(0)
    return ""


def stripe_checkout_id(*blobs: Any) -> str:
    return _first_id(_CS_ID, *blobs)


def openai_internal_checkout_id(*blobs: Any) -> str:
    """ChatGPT `/payments/checkout/confirm` 只接受内部 oaics_ 会话。"""
    return _first_id(_OAICS_ID, *blobs)


def public_checkout_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("http"):
        text = text.rstrip("/").split("/")[-1]
    return text.split("?")[0].split("#")[0]


def stripe_verify_url(
    checkout_id: str,
    *,
    processor: str = "",
    plan: str = "",
    source: str = "chatgpt_web_merged",
) -> str:
    """HAR 里 PI confirm 的 return_url：/checkout/verify?stripe_session_id=oaics_…"""
    session_id = str(checkout_id or "").strip().rstrip("/").split("/")[-1]
    if session_id.startswith("http") or not session_id:
        return f"{APP_BASE}/"
    query = [f"stripe_session_id={session_id}"]
    entity = str(processor or "").strip()
    if entity and entity not in {"verify", "c", "pay"}:
        query.append(f"processor_entity={entity}")
    if source:
        query.append(f"source={source}")
    plan_type = _PLAN_TYPE.get(str(plan), "")
    if plan_type:
        query.append(f"plan_type={plan_type}")
    return f"{APP_BASE}/checkout/verify?{'&'.join(query)}"


def hosted_checkout_url(url: str = "", session_id: str = "") -> str:
    """Team 托管长链：pay.openai.com/c/pay/{cs_live} + Checkout 片段。"""
    value = str(url or "").strip()
    cs_id = session_id if str(session_id).startswith("cs_") else stripe_checkout_id(value, session_id)
    if value.startswith("https://checkout.stripe.com/c/pay/"):
        value = "https://pay.openai.com" + value[len("https://checkout.stripe.com") :]
    if value.startswith("https://pay.openai.com/c/pay/"):
        if "#" not in value:
            return value + _HOSTED_CHECKOUT_FRAGMENT
        return value
    if cs_id:
        return f"https://pay.openai.com/c/pay/{cs_id}{_HOSTED_CHECKOUT_FRAGMENT}"
    return value


# HAR（绑卡chatgpt.com.har）里 payments/checkout 与 checkout/confirm 请求都带这组前端标识。
_CODEX_WEB_HEADERS = {
    "originator": "Codex Browser",
    "x-openai-web-frontend": "codex_webview",
    "x-openai-codex-window-type": "browser",
    "x-oai-mcp-form-version": "2",
    "x-openai-checkout-source": "chatgpt_web_merged",
}


def _checkout_body(
    *,
    plan: str,
    country: str,
    currency: str,
    promo: bool = False,
    promo_code: str = "",
    workspace_name: str = "",
    seat_quantity: int = 5,
    price_interval: str = "month",
) -> Dict[str, Any]:
    if str(plan) == "team":
        seats = clamp_team_seats(seat_quantity)
        interval = "year" if str(price_interval).lower() == "year" else "month"
        body: Dict[str, Any] = {
            "entry_point": "team_workspace_purchase_modal",
            "plan_name": "chatgptteamplan",
            "billing_details": {"country": country, "currency": currency},
            "cancel_url": f"{APP_BASE}/",
            "checkout_ui_mode": "redirect",
            "check_card_proxy": True,
            "team_plan_data": {
                "workspace_name": (workspace_name or "Team Workspace")[:80],
                "price_interval": interval,
                "seat_quantity": seats,
            },
        }
        code = str(promo_code or "").strip()
        if code:
            body["promo_code"] = code[:80]
        return body
    body = {
        "entry_point": "all_plans_pricing_modal",
        "plan_name": _PLAN_NAME.get(str(plan), "chatgptplusplan"),
        "billing_details": {"country": country, "currency": currency},
        "checkout_source": "chatgpt_web_merged",
        "supports_saved_payment_link": True,
        "checkout_appearance": "light",
        "cancel_url": f"{APP_BASE}/?cta_tab=personal",
        "purchase_attempt_id": str(uuid.uuid4()),
    }
    if promo:
        body["promo_campaign"] = {
            "promo_campaign_id": "plus-1-month-free",
            "is_coupon_from_query_param": False,
        }
    return body


@dataclass
class CheckoutSession:
    checkout_session_id: str
    publishable_key: str
    account_id: str
    checkout_url: str
    currency: str
    amount: Optional[Decimal] = None
    processor_entity: str = ""
    attestation: str = ""
    client_build_number: str = ""
    client_version: str = ""
    oai_session_id: str = ""
    customer_session_client_secret: str = ""
    checkout_kind: str = "custom"
    confirm_return_url: str = ""


def jwt_account_id(access_token: str) -> str:
    parts = str(access_token or "").split(".")
    if len(parts) < 2:
        return ""
    try:
        padded = parts[1] + ("=" * (-len(parts[1]) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        value = auth.get("chatgpt_account_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _new_session(*, proxy: Optional[str], timeout: float, impersonate: str = _IMPERSONATE):
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError as exc:  # pragma: no cover
        raise DomainError(
            ErrorCode.CHECKOUT_UPSTREAM_ERROR,
            "缺少 curl_cffi，无法用浏览器指纹请求 ChatGPT",
        ) from exc
    try:
        session = CurlSession(impersonate=impersonate, timeout=timeout)
    except Exception:
        session = CurlSession(impersonate="chrome136", timeout=timeout)
    if hasattr(session, "trust_env"):
        session.trust_env = False
    proxy = str(proxy or "").strip()
    session.proxies = {"http": proxy, "https": proxy} if proxy else {}
    return session


@dataclass
class ChatGPTClient:
    access_token: str
    proxy: Optional[str] = None
    timeout: float = 90.0
    account_id: str = ""
    attestation: str = ""
    client_build_number: str = _CLIENT_BUILD
    client_version: str = _CLIENT_VERSION
    oai_session_id: str = ""
    session_token: str = ""
    device_id: str = ""
    extra_cookies: Dict[str, str] = field(default_factory=dict)
    language: str = "en-US"
    timezone: str = "America/New_York"
    sentinel_token: str = ""
    sentinel_so: str = ""
    _http: Any = field(default=None, repr=False)
    _stripe_http: Any = field(default=None, repr=False)

    @classmethod
    def from_raw_session(cls, raw: str, proxy: Optional[str] = None) -> "ChatGPTClient":
        bundle: SessionBundle = parse_session_bundle(raw)
        token = bundle.access_token
        device = bundle.device_id or str(uuid.uuid5(uuid.NAMESPACE_URL, "dcp-did:" + token))
        session_id = bundle.oai_session_id or str(uuid.uuid5(uuid.NAMESPACE_URL, "dcp-sid:" + token))
        return cls(
            access_token=token,
            proxy=proxy,
            account_id=jwt_account_id(token),
            session_token=bundle.session_token,
            device_id=device,
            extra_cookies=dict(bundle.cookies),
            oai_session_id=session_id,
        )

    def _cookie_header(self) -> str:
        values: Dict[str, str] = dict(self.extra_cookies)
        if self.session_token:
            values.setdefault("__Secure-next-auth.session-token", self.session_token)
        if self.device_id:
            values["oai-did"] = self.device_id
        return "; ".join(f"{name}={value}" for name, value in values.items() if name and value is not None)

    def _identity_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": _CHROME,
            "Accept": "*/*",
            "Accept-Language": f"{self.language},{self.language.split('-')[0]};q=0.9,en;q=0.8",
            "Authorization": f"Bearer {self.access_token}",
            "Origin": APP_BASE,
            "Referer": f"{APP_BASE}/",
            "Content-Type": "application/json",
            "oai-did": self.device_id,
            "oai-device-id": self.device_id,
            "oai-language": self.language,
            "oai-telemetry": "production",
            "oai-session-id": self.oai_session_id,
            "oai-client-version": self.client_version,
            "oai-client-build-number": self.client_build_number,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sec-ch-ua": _SEC_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Cookie": self._cookie_header(),
        }
        if self.account_id:
            headers["chatgpt-account-id"] = self.account_id
        return headers

    def _route_headers(self, route: str, *, page_url: str = "") -> Dict[str, str]:
        headers = {
            "Referer": page_url or f"{APP_BASE}/",
            "x-openai-target-path": route,
            "x-openai-target-route": route,
        }
        if route.startswith("/backend-api/payments/"):
            headers.update(_CODEX_WEB_HEADERS)
        if route.startswith("/backend-api/payments/") and self.attestation:
            headers["oai-web-deployment-attestation"] = self.attestation
            headers["OAI-Web-Deployment-Attestation"] = self.attestation
        if self.sentinel_token:
            headers["openai-sentinel-token"] = self.sentinel_token
            headers["OpenAI-Sentinel-Token"] = self.sentinel_token
        if self.sentinel_so:
            headers["openai-sentinel-so-token"] = self.sentinel_so
            headers["OpenAI-Sentinel-SO-Token"] = self.sentinel_so
        return headers

    def _merge_cookies(self) -> None:
        jar = getattr(self.http, "cookies", None)
        if jar is None:
            return
        gathered: Dict[str, str] = {}
        try:
            getter = getattr(jar, "get_dict", None)
            if callable(getter):
                gathered.update(getter() or {})
                for domain in ("chatgpt.com", ".chatgpt.com"):
                    try:
                        gathered.update(getter(domain=domain) or {})
                    except TypeError:
                        break
                    except Exception:
                        continue
            elif hasattr(jar, "items"):
                gathered.update({str(k): str(v) for k, v in jar.items()})
        except Exception:
            gathered = {}
        for name, value in gathered.items():
            if name and value is not None:
                self.extra_cookies[str(name)] = str(value)
        self.http.headers.update(self._identity_headers())

    def warmup(self, *, page_url: str = "") -> None:
        url = page_url or f"{APP_BASE}/"
        headers = self._identity_headers()
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        headers["Referer"] = url
        headers["sec-fetch-dest"] = "document"
        headers["sec-fetch-mode"] = "navigate"
        headers["upgrade-insecure-requests"] = "1"
        headers.pop("Content-Type", None)
        try:
            home = self.http.get(url, headers=headers, timeout=self.timeout)
        except Exception:
            return
        html = str(getattr(home, "text", "") or "")
        version, build, session_id = extract_build(html)
        if version:
            self.client_version = version
        if build:
            self.client_build_number = build
        if session_id:
            self.oai_session_id = session_id
        attestation = extract_attestation(html)
        if attestation:
            self.attestation = attestation
        self._merge_cookies()

    def mint_sentinel(self, *, flow: str, page_url: str = "") -> None:
        token = mint(
            flow=flow,
            device_id=self.device_id,
            user_agent=_CHROME,
            proxy=self.proxy or "",
            page_url=page_url or f"{APP_BASE}/",
            language=self.language,
            timezone=self.timezone,
            cookie_header=self._cookie_header(),
            timeout_s=max(30.0, min(self.timeout, 90.0)),
        )
        value = header_value(token)
        if not value:
            raise DomainError(
                ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                "无法签发 ChatGPT 风控令牌（Sentinel）。请确认容器里有 Node，且出口代理可用。",
            )
        self.sentinel_token = value
        self.sentinel_so = so_header_value(token)

    def prepare_risk(self, *, flow: str, page_url: str = "", country: str = "") -> None:
        if country:
            self.language = locale_for(country)
            self.timezone = timezone_for(country)
        url = page_url or f"{APP_BASE}/"
        self.warmup(page_url=url)
        self.mint_sentinel(flow=flow, page_url=url)

    @property
    def http(self):
        if self._http is None:
            self._http = _new_session(proxy=self.proxy, timeout=self.timeout)
            jar = getattr(self._http, "cookies", None)
            setter = getattr(jar, "set", None) if jar is not None else None
            if callable(setter):
                cookies = dict(self.extra_cookies)
                if self.session_token:
                    cookies.setdefault("__Secure-next-auth.session-token", self.session_token)
                if self.device_id:
                    cookies["oai-did"] = self.device_id
                for name, value in cookies.items():
                    if not name or value is None:
                        continue
                    try:
                        setter(str(name), str(value), domain="chatgpt.com")
                    except TypeError:
                        try:
                            setter(str(name), str(value))
                        except Exception:
                            continue
                    except Exception:
                        continue
            self._http.headers.update(self._identity_headers())
        return self._http

    @property
    def stripe_http(self):
        if self._stripe_http is None:
            self._stripe_http = _new_session(proxy=self.proxy, timeout=self.timeout)
            self._stripe_http.headers.update(
                {
                    "User-Agent": _CHROME,
                    "Origin": "https://js.stripe.com",
                    "Referer": "https://js.stripe.com/",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            )
        return self._stripe_http

    def close(self) -> None:
        for handle in (self._http, self._stripe_http):
            if handle is not None:
                closer = getattr(handle, "close", None)
                if callable(closer):
                    closer()
        self._http = None
        self._stripe_http = None

    def _raise(self, code: ErrorCode, response: Any, prefix: str) -> None:
        body = redact_sensitive(str(getattr(response, "text", ""))[:500])
        status = int(getattr(response, "status_code", 0) or 0)
        lowered = body.lower()
        if status == 401:
            raise DomainError(ErrorCode.INVALID_SESSION, f"{prefix}: session 无效或已过期")
        if "unusual activity" in lowered:
            raise DomainError(
                ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                "ChatGPT 判定异常流量。请换一个同国家 SID 节点，"
                "或用与账单国家相同网络导出的新 session 再试。",
            )
        if "billing country must match" in lowered:
            raise DomainError(
                ErrorCode.BILLING_COUNTRY_MISMATCH,
                "账单国家必须与出口代理国家一致，请用所选地区的 SID 重试。",
            )
        if "already paid" in lowered:
            raise DomainError(code, f"{prefix}: 该账号已是付费订阅")
        if "only for internal checkout sessions" in lowered:
            raise DomainError(
                code,
                "ChatGPT 内部确认只接受 oaics_ 会话。当前是 Stripe cs_ 自定义结账，不能调用 /payments/checkout/confirm。",
            )
        if status == 403:
            raise DomainError(code, f"{prefix}: 被拦截（HTTP 403），请检查出口代理是否可用")
        if status >= 500:
            raise DomainError(code, f"{prefix}失败：ChatGPT 暂时返回 {status}，请换档位或稍后重试")
        raise DomainError(code, f"{prefix}: HTTP {status} {body}")

    def hydrate(self) -> None:
        if not self.account_id:
            self.account_id = jwt_account_id(self.access_token)
        if self.account_id:
            return
        me = self.http.get(
            f"{APP_BASE}/backend-api/me",
            headers=self._route_headers("/backend-api/me"),
            timeout=self.timeout,
        )
        if int(getattr(me, "status_code", 0) or 0) == 401:
            raise DomainError(ErrorCode.INVALID_SESSION, "Session 无效或已过期")
        if int(getattr(me, "status_code", 0) or 0) >= 400:
            check = self.http.get(
                f"{APP_BASE}/backend-api/accounts/check",
                headers=self._route_headers("/backend-api/accounts/check"),
                timeout=self.timeout,
            )
            if int(getattr(check, "status_code", 0) or 0) == 401:
                raise DomainError(ErrorCode.INVALID_SESSION, "Session 无效或已过期")
            if int(getattr(check, "status_code", 0) or 0) >= 400:
                self._raise(ErrorCode.INVALID_SESSION, me, "读取账号")
            payload = _json(check)
        else:
            payload = _json(me)
        self.account_id = _account_id(payload)
        if not self.account_id:
            raise DomainError(ErrorCode.INVALID_SESSION, "无法从 session 解析账号 id")
        self.http.headers.update(self._identity_headers())

    def create_checkout(
        self,
        *,
        plan: str,
        country: str,
        promo: bool = False,
        promo_code: str = "",
        workspace_name: str = "",
        seat_quantity: int = 5,
        price_interval: str = "month",
    ) -> CheckoutSession:
        country = country.upper()
        currency = currency_for(country)
        hosted = str(plan) == "team"
        page_url = f"{APP_BASE}/?promo_campaign=plus-1-month-free" if promo else f"{APP_BASE}/"
        self.prepare_risk(flow="chatgpt_checkout", page_url=page_url, country=country)
        if not self.account_id:
            self.hydrate()
        if self._http is not None:
            self._http.headers.update(self._identity_headers())
        body = _checkout_body(
            plan=plan,
            country=country,
            currency=currency,
            promo=promo,
            promo_code=promo_code,
            workspace_name=workspace_name,
            seat_quantity=seat_quantity,
            price_interval=price_interval,
        )
        response = self.http.post(
            f"{APP_BASE}/backend-api/payments/checkout",
            json=body,
            headers=self._route_headers("/backend-api/payments/checkout", page_url=page_url),
            timeout=self.timeout,
        )
        if int(getattr(response, "status_code", 0) or 0) == 401:
            raise DomainError(ErrorCode.INVALID_SESSION, "Session 无效或已过期")
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            self._raise(ErrorCode.CHECKOUT_UPSTREAM_ERROR, response, "创建结账")
        payload = _json(response)
        raw_url = str(payload.get("url") or payload.get("checkout_url") or "").strip()
        checkout_id = public_checkout_id(
            payload.get("checkout_session_id") or payload.get("session_id") or payload.get("id") or ""
        )
        stripe_id = stripe_checkout_id(payload, raw_url, checkout_id)
        internal_id = openai_internal_checkout_id(payload, raw_url, checkout_id)
        if hosted:
            url = hosted_checkout_url(raw_url, stripe_id or checkout_id)
            if not url:
                raise DomainError(ErrorCode.CHECKOUT_UPSTREAM_ERROR, "未拿到 Team 托管长链")
            session_id = stripe_id or checkout_id
        else:
            # 官方晚间 SPA 常把 cs_live 放在顶层 id；内部 confirm 仍要 oaics_（若响应里有）。
            session_id = internal_id or checkout_id or stripe_id
            if not session_id:
                raise DomainError(
                    ErrorCode.CHECKOUT_UPSTREAM_ERROR,
                    f"结账响应缺少 session id: {redact_sensitive(str(payload)[:240])}",
                )
            processor = str(payload.get("processor_entity") or _processor(country))
            path_id = stripe_id if (session_id.startswith("oaics_") and stripe_id) else session_id
            url = raw_url if raw_url.startswith("http") else f"{APP_BASE}/checkout/{processor}/{path_id}"
        processor = str(payload.get("processor_entity") or _processor(country))
        logger.info(
            "checkout_session_kind=%s processor=%s hosted=%s",
            session_id.split("_", 1)[0] + "_" if "_" in session_id else "?",
            processor,
            hosted,
        )
        confirm_return = str(payload.get("confirm_return_url") or "").strip()
        if not hosted and not confirm_return:
            confirm_return = stripe_verify_url(session_id, processor=processor, plan=plan)
        pk = str(payload.get("publishable_key") or payload.get("publishableKey") or "").strip()
        if not pk.startswith(("pk_live_", "pk_test_")):
            pk = "" if hosted else self._publishable_key()
        page = url if str(url).startswith("http") else page_url
        amount, quote_currency = quote_from_payload(payload, currency)
        if not hosted:
            refreshed, refreshed_currency = self._quote_from_context(
                processor=processor, checkout_id=session_id, page_url=page, currency=quote_currency or currency
            )
            if refreshed is not None:
                amount, quote_currency = refreshed, refreshed_currency
            billing = address_for(country)
            taxed, taxed_currency = self._quote_from_taxes(
                checkout_id=session_id,
                page_url=page,
                currency=quote_currency or currency,
                billing=billing,
                processor=processor,
            )
            if taxed is not None:
                amount, quote_currency = taxed, taxed_currency
        customer_session = str(
            payload.get("customer_session_client_secret")
            or payload.get("customerSessionClientSecret")
            or ""
        ).strip()
        return CheckoutSession(
            checkout_session_id=session_id,
            publishable_key=pk,
            account_id=self.account_id,
            checkout_url=url,
            currency=quote_currency or currency,
            amount=amount,
            processor_entity=processor,
            attestation=self.attestation,
            client_build_number=self.client_build_number,
            client_version=self.client_version,
            oai_session_id=self.oai_session_id,
            customer_session_client_secret=customer_session,
            checkout_kind="hosted" if hosted else "custom",
            confirm_return_url="" if hosted else confirm_return,
        )

    def _publishable_key(self) -> str:
        response = self.http.get(
            f"{APP_BASE}/backend-api/payments/stripe_client_bootstrap",
            params={"account_id": self.account_id},
            headers=self._route_headers("/backend-api/payments/stripe_client_bootstrap"),
            timeout=self.timeout,
        )
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            self._raise(ErrorCode.CHECKOUT_UPSTREAM_ERROR, response, "读取 Stripe 公钥")
        payload = _json(response)
        key = str(payload.get("publishable_key") or payload.get("publishableKey") or "")
        if not key.startswith(("pk_live_", "pk_test_")):
            raise DomainError(ErrorCode.CHECKOUT_UPSTREAM_ERROR, "未拿到 Stripe 公钥")
        return key

    def _quote_from_context(
        self, *, processor: str, checkout_id: str, page_url: str, currency: str
    ) -> tuple[Optional[Decimal], str]:
        entities: list[str] = []
        for entity in (processor, "openai_llc", "openai_ie"):
            if entity and entity not in entities:
                entities.append(entity)
        routes = [f"/backend-api/payments/checkout/{entity}/{checkout_id}" for entity in entities]
        routes.append(f"/backend-api/payments/checkout/{checkout_id}")
        for route in routes:
            try:
                response = self.http.get(
                    f"{APP_BASE}{route}",
                    headers=self._route_headers(route, page_url=page_url),
                    timeout=self.timeout,
                )
            except Exception:
                continue
            if int(getattr(response, "status_code", 0) or 0) >= 400:
                continue
            amount, found = quote_from_payload(_json(response), currency)
            if amount is not None:
                return amount, found or currency
        return None, currency

    def _quote_from_taxes(
        self,
        *,
        checkout_id: str,
        page_url: str,
        currency: str,
        billing: Optional[Dict[str, str]] = None,
        processor: str = "",
    ) -> tuple[Optional[Decimal], str]:
        try:
            response = self.http.post(
                f"{APP_BASE}/backend-api/payments/checkout/taxes",
                json=_taxes_body(
                    checkout_id=checkout_id,
                    billing=billing,
                    processor=processor,
                    currency=currency,
                ),
                headers=self._route_headers("/backend-api/payments/checkout/taxes", page_url=page_url),
                timeout=self.timeout,
            )
        except Exception:
            return None, currency
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            return None, currency
        return quote_from_payload(_json(response), currency)

    def prepare_setup_intent(self) -> tuple[str, str]:
        if not self.account_id:
            self.hydrate()
        response = self.http.post(
            f"{APP_BASE}/backend-api/payments/payment_method",
            json={"account_id": self.account_id},
            headers=self._route_headers("/backend-api/payments/payment_method"),
            timeout=self.timeout,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 401:
            raise DomainError(ErrorCode.INVALID_SESSION, "Session 无效或已过期")
        if status >= 400:
            self._raise(ErrorCode.PAYMENT_UNKNOWN_STATE, response, "准备支付方式")
        return setup_intent_from_payload(_json(response))

    def confirm_setup_intent(
        self, *, setup_id: str, client_secret: str, payment_method: str, publishable_key: str
    ) -> Dict[str, Any]:
        body = {
            "key": publishable_key,
            "client_secret": client_secret,
            "payment_method": payment_method,
        }
        response = self.stripe_http.post(
            f"{STRIPE_BASE}/v1/setup_intents/{setup_id}/confirm",
            data=urlencode(body),
            timeout=self.timeout,
        )
        payload = _json(response)
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            message = (
                (payload.get("error") or {}).get("message")
                if isinstance(payload.get("error"), dict)
                else payload.get("message")
            )
            text = str(message or f"Stripe confirm HTTP {response.status_code}")
            if "billing country must match" in text.lower():
                raise DomainError(
                    ErrorCode.BILLING_COUNTRY_MISMATCH,
                    "账单国家必须与出口代理国家一致，请用所选地区的 SID 重试。",
                )
            raise DomainError(ErrorCode.PAYMENT_DECLINED, redact_sensitive(text))
        return payload

    def create_confirmation_token(self, *, publishable_key: str, payment_method: str) -> str:
        body = {
            "key": publishable_key,
            "payment_method": payment_method,
            "setup_future_usage": "off_session",
            "_stripe_version": STRIPE_API_VERSION,
        }
        response = self.stripe_http.post(
            f"{STRIPE_BASE}/v1/confirmation_tokens",
            data=urlencode(body),
            timeout=self.timeout,
        )
        payload = _json(response)
        token = str(payload.get("id") or "")
        if int(getattr(response, "status_code", 0) or 0) >= 400 or not token:
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            message = str(error.get("message") or payload.get("message") or "创建 confirmation token 失败")
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, redact_sensitive(message))
        return token

    def confirm_checkout(
        self,
        *,
        checkout_session_id: str,
        confirm_token: str,
        checkout_url: str = "",
        billing: Optional[Dict[str, str]] = None,
        processor_entity: str = "",
        currency: str = "",
        publishable_key: str = "",
    ) -> Dict[str, Any]:
        session_id = public_checkout_id(checkout_session_id)
        if session_id.startswith("cs_"):
            return self.confirm_stripe_custom_checkout(
                checkout_session_id=session_id,
                publishable_key=publishable_key,
                confirmation_token=confirm_token,
                return_url=stripe_verify_url(
                    session_id,
                    processor=processor_entity or _processor_from_checkout_url(checkout_url),
                ),
            )
        page_url = checkout_url or f"{APP_BASE}/checkout/{session_id}"
        self.mint_sentinel(flow="checkout_session_approval", page_url=page_url)
        processor = processor_entity or _processor_from_checkout_url(checkout_url)
        self.http.post(
            f"{APP_BASE}/backend-api/payments/checkout/taxes",
            json=_taxes_body(
                checkout_id=session_id,
                billing=billing,
                processor=processor,
                currency=currency,
            ),
            headers=self._route_headers("/backend-api/payments/checkout/taxes", page_url=page_url),
            timeout=self.timeout,
        )
        try:
            self.http.post(
                f"{APP_BASE}/backend-api/payments/checkout/update_tax_id",
                json={"checkout_session_id": session_id, "tax_id_info": None},
                headers=self._route_headers(
                    "/backend-api/payments/checkout/update_tax_id", page_url=page_url
                ),
                timeout=self.timeout,
            )
        except Exception:
            pass
        response = self.http.post(
            f"{APP_BASE}/backend-api/payments/checkout/confirm",
            json={
                "checkout_session_id": session_id,
                "confirm_token": confirm_token,
                "selected_payment_method_type": "card",
            },
            headers=self._route_headers("/backend-api/payments/checkout/confirm", page_url=page_url),
            timeout=self.timeout,
        )
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            self._raise(ErrorCode.PAYMENT_UNKNOWN_STATE, response, "确认结账")
        payload = _json(response)
        logger.info(
            "checkout_confirm status=%s type=%s has_secret=%s",
            payload.get("status") or payload.get("result") or "",
            payload.get("type") or "",
            bool(payload.get("client_secret")),
        )
        return payload

    def confirm_stripe_custom_checkout(
        self,
        *,
        checkout_session_id: str,
        publishable_key: str,
        confirmation_token: str,
        return_url: str = "",
    ) -> Dict[str, Any]:
        """官方晚间 Plus/Go/Pro SPA：cs_live 走 Stripe payment_pages，不能 POST ChatGPT confirm。"""
        session_id = public_checkout_id(checkout_session_id)
        pk = str(publishable_key or "").strip()
        token = str(confirmation_token or "").strip()
        if not session_id.startswith("cs_"):
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "Stripe Custom Checkout 需要 cs_ 会话")
        if not pk.startswith(("pk_live_", "pk_test_")):
            raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, "缺少 Stripe 公钥")
        if not token.startswith("ctoken_"):
            raise DomainError(ErrorCode.PAYMENT_DECLINED, "缺少 confirmation token")
        init_payload = self._post_stripe_form(
            f"{STRIPE_BASE}/v1/payment_pages/{session_id}/init",
            {
                "browser_locale": self.language or "en-US",
                "browser_timezone": self.timezone or "America/New_York",
                "elements_session_client[elements_init_source]": "custom_checkout",
                "elements_session_client[referrer_host]": "chatgpt.com",
                "elements_session_client[stripe_js_id]": str(uuid.uuid4()),
                "elements_session_client[locale]": str((self.language or "en-US").split("-")[0] or "en"),
                "elements_session_client[is_aggregation_expected]": "false",
                "key": pk,
                "_stripe_version": STRIPE_CHECKOUT_API_VERSION,
            },
        )
        confirm_body: Dict[str, str] = {
            "key": pk,
            "_stripe_version": STRIPE_CHECKOUT_API_VERSION,
            "confirmation_token": token,
            "expected_payment_method_type": "card",
            "return_url": return_url or stripe_verify_url(session_id),
            "consent[terms_of_service]": "accepted",
        }
        checksum = str(init_payload.get("init_checksum") or "")
        if checksum:
            confirm_body["init_checksum"] = checksum
        minor = expected_amount_minor(init_payload)
        if minor is None:
            raise DomainError(
                ErrorCode.PAYMENT_UNKNOWN_STATE,
                "Stripe 确认缺少应付金额（expected_amount）。请重新创建结账后再确认。",
            )
        confirm_body["expected_amount"] = str(minor)
        payload = self._post_stripe_form(
            f"{STRIPE_BASE}/v1/payment_pages/{session_id}/confirm",
            confirm_body,
        )
        logger.info(
            "stripe_payment_page_confirm status=%s submission=%s has_pi=%s",
            payload.get("status") or "",
            submission_state(payload),
            bool(_intent_object(payload)),
        )
        return payload

    def finalize_stripe_custom_checkout(
        self,
        *,
        checkout_session_id: str,
        publishable_key: str,
        checkout_url: str = "",
        processor_entity: str = "",
        confirmed: Optional[Dict[str, Any]] = None,
        attempts: int = 12,
        interval: float = 0.8,
    ) -> Dict[str, Any]:
        """cs_live confirm 之后：ChatGPT approve（requires_approval）再轮询 payment_pages。"""
        page = dict(confirmed or {})
        if checkout_requires_approval(page):
            approved = self.approve_checkout(
                checkout_session_id=checkout_session_id,
                processor_entity=processor_entity,
                checkout_url=checkout_url,
            )
            logger.info(
                "checkout_approve result=%s status=%s",
                approved.get("result") or "",
                approved.get("status") or "",
            )
            if checkout_confirm_blocked(approved):
                page["status"] = str(approved.get("status") or "blocked")
                page["result"] = str(approved.get("result") or "blocked")
                extra = checkout_confirm_message(approved)
                if extra:
                    page["message"] = extra
                return page
        if payment_page_settled(page):
            return page
        polled = self.poll_payment_page(
            checkout_session_id=checkout_session_id,
            publishable_key=publishable_key,
            attempts=attempts,
            interval=interval,
        )
        return polled or page

    def poll_payment_page(
        self,
        *,
        checkout_session_id: str,
        publishable_key: str,
        attempts: int = 12,
        interval: float = 0.8,
    ) -> Dict[str, Any]:
        session_id = public_checkout_id(checkout_session_id)
        pk = str(publishable_key or "").strip()
        getter = getattr(self.stripe_http, "get", None)
        if not session_id.startswith("cs_") or not callable(getter):
            return {}
        params = {
            "key": pk,
            "_stripe_version": STRIPE_CHECKOUT_API_VERSION,
            "elements_session_client[elements_init_source]": "custom_checkout",
            "elements_session_client[referrer_host]": "chatgpt.com",
            "elements_session_client[locale]": str((self.language or "en-US").split("-")[0] or "en"),
            "elements_session_client[is_aggregation_expected]": "false",
        }
        last: Dict[str, Any] = {}
        for _ in range(max(1, attempts)):
            response = getter(
                f"{STRIPE_BASE}/v1/payment_pages/{session_id}",
                params=params,
                timeout=self.timeout,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            payload = _json(response)
            if status < 400 and payload:
                last = payload
                logger.info(
                    "stripe_payment_page_poll status=%s submission=%s has_pi=%s",
                    payload.get("status") or "",
                    submission_state(payload),
                    bool(_intent_object(payload)),
                )
                if submission_state(payload) in {"failed", "declined", "canceled", "cancelled"}:
                    attempt = payload.get("submission_attempt")
                    logger.warning(
                        "stripe_submission_failed detail=%s attempt_keys=%s",
                        submission_failure_detail(payload) or "-",
                        sorted(attempt) if isinstance(attempt, dict) else [],
                    )
                if payment_page_settled(payload):
                    return payload
            if interval > 0:
                time.sleep(interval)
        return last

    def approve_checkout(
        self,
        *,
        checkout_session_id: str,
        processor_entity: str = "",
        checkout_url: str = "",
    ) -> Dict[str, Any]:
        session_id = public_checkout_id(checkout_session_id)
        processor = processor_entity or _processor_from_checkout_url(checkout_url) or _processor("")
        page_url = checkout_url or f"{APP_BASE}/checkout/{processor}/{session_id}"
        self.mint_sentinel(flow="checkout_session_approval", page_url=page_url)
        headers = self._route_headers("/backend-api/payments/checkout/approve", page_url=page_url)
        headers["x-oai-is-client-observation"] = "true"
        response = self.http.post(
            f"{APP_BASE}/backend-api/payments/checkout/approve",
            json={"checkout_session_id": session_id, "processor_entity": processor},
            headers=headers,
            timeout=self.timeout,
        )
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            self._raise(ErrorCode.PAYMENT_UNKNOWN_STATE, response, "批准结账")
        return _json(response)

    def _post_stripe_form(self, url: str, body: Dict[str, str]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        status = 0
        data = dict(body)
        for _ in range(8):
            response = self.stripe_http.post(
                url,
                data=urlencode(data),
                timeout=self.timeout,
            )
            payload = _json(response)
            status = int(getattr(response, "status_code", 0) or 0)
            if status != 400:
                break
            unknown = _stripe_unknown_param(payload)
            if not unknown:
                break
            removed = False
            for key in list(data):
                if key == unknown or key.startswith(unknown + "["):
                    data.pop(key, None)
                    removed = True
            if not removed:
                break
        if status >= 400:
            _raise_stripe(payload, status)
        return payload

    def confirm_stripe_intent(
        self,
        *,
        intent_id: str,
        client_secret: str,
        publishable_key: str,
        payment_method: str = "",
        confirmation_token: str = "",
        return_url: str = "",
    ) -> Dict[str, Any]:
        intent_id = intent_id or intent_id_from_secret(client_secret)
        kind = "payment_intents" if intent_id.startswith("pi_") else "setup_intents"
        body: Dict[str, str] = {
            "key": publishable_key,
            "client_secret": client_secret,
            "_stripe_version": STRIPE_API_VERSION,
        }
        if confirmation_token:
            body["confirmation_token"] = confirmation_token
        elif payment_method:
            body["payment_method"] = payment_method
        if return_url:
            body["return_url"] = return_url
        response = self.stripe_http.post(
            f"{STRIPE_BASE}/v1/{kind}/{intent_id}/confirm",
            data=urlencode(body),
            timeout=self.timeout,
        )
        payload = _json(response)
        status = int(getattr(response, "status_code", 0) or 0)
        if status >= 400:
            _raise_stripe(payload, status)
        return payload

    def subscription_payload(self) -> Dict[str, Any]:
        if not self.account_id:
            self.hydrate()
        response = self.http.get(
            f"{APP_BASE}/backend-api/subscriptions",
            headers=self._route_headers("/backend-api/subscriptions"),
            timeout=self.timeout,
        )
        if int(getattr(response, "status_code", 0) or 0) == 401:
            raise DomainError(ErrorCode.INVALID_SESSION, "Session 无效或已过期")
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            self._raise(ErrorCode.SUBSCRIPTION_NOT_ACTIVE, response, "查询订阅")
        return _json(response)


def _json(response: Any) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _account_id(payload: Dict[str, Any]) -> str:
    for key in ("account_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    account = payload.get("account")
    if isinstance(account, dict):
        for key in ("id", "account_id"):
            value = account.get(key)
            if isinstance(value, str) and value:
                return value
    orgs = payload.get("orgs") or payload.get("accounts")
    if isinstance(orgs, dict):
        data = orgs.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            value = data[0].get("id")
            if isinstance(value, str):
                return value
    return ""


def _processor(_country: str) -> str:
    # HAR：日本结账的 processor_entity 也是 openai_llc，不是 openai_ie。
    return "openai_llc"


def _processor_from_checkout_url(url: str) -> str:
    parts = [part for part in str(url or "").split("/") if part]
    if "checkout" not in parts:
        return ""
    index = parts.index("checkout")
    if index + 1 >= len(parts):
        return ""
    candidate = parts[index + 1]
    if candidate in {"verify", ""} or candidate.startswith("oaics_"):
        return ""
    return candidate


def _taxes_body(
    *,
    checkout_id: str,
    billing: Optional[Dict[str, str]] = None,
    processor: str = "",
    currency: str = "",
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"checkout_session_id": checkout_id, "tax_id": None}
    if processor:
        body["processor_entity"] = processor
    if currency:
        body["currency"] = currency
    if billing:
        body["billing_country"] = billing.get("country") or ""
        body["billing_name"] = billing.get("name") or ""
        body["billing_address"] = {
            "line1": billing.get("line1") or "",
            "city": billing.get("city") or "",
            "state": billing.get("state") or "",
            "postal_code": billing.get("postal_code") or "",
            "country": billing.get("country") or "",
        }
    return body


def intent_id_from_secret(secret: str) -> str:
    text = str(secret or "").strip()
    marker = "_secret_"
    if marker not in text:
        return ""
    prefix = text.split(marker, 1)[0]
    if prefix.startswith(("pi_", "seti_")):
        return prefix
    return ""


_CONFIRM_BLOCKED = frozenset({"blocked", "failed", "rejected", "not_approved", "declined"})


def checkout_confirm_blocked(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or payload.get("result") or "").strip().lower()
    return status in _CONFIRM_BLOCKED


def checkout_confirm_message(payload: Dict[str, Any]) -> str:
    for key in ("message", "detail", "reason", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and value.strip().lower() not in _CONFIRM_BLOCKED:
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("message") or value.get("code") or value.get("reason")
            if nested:
                return str(nested)
    return ""


def checkout_confirm_blocked_advice(country: str = "") -> str:
    code = str(country or "").strip().upper()
    if code == "US":
        return (
            "ChatGPT 未批准这次支付（blocked）。不是发卡行拒卡。"
            "美国单走美元。若 session 是日本网络/日本刀导出的，不能选美国。"
            "已被 blocked 的同一条 session 换国家再付一次通常仍会 blocked，需要重新导出后再开一单。"
        )
    if code == "JP":
        return (
            "ChatGPT 未批准这次支付（blocked）。不是发卡行拒卡。"
            "日本地区已按日元结账，但这个账号或设备仍被风控。"
            "同一条已 blocked 的 session 再付一次没用，请在日本网络重新导出整段 session，地区继续选日本。"
        )
    return (
        "ChatGPT 未批准这次支付（blocked）。不是发卡行拒卡，是账号/地区风控。"
        "账单国家必须和 session 导出国家一致。已被 blocked 的 session 不要换国家重试，需要新导出。"
    )


def payment_intent_from_confirm(payload: Dict[str, Any]) -> tuple[str, str, str]:
    """ChatGPT checkout/confirm 成功时返回 status=success + pi client_secret，没有顶层 id。

    Stripe payment_pages/confirm 则把 PaymentIntent 嵌在 ``payment_intent`` 里，
    批准前也可能只给 ``pi_`` 字符串。
    """
    nested = _intent_object(payload)
    secret = str(payload.get("client_secret") or nested.get("client_secret") or "")
    intent_id = str(nested.get("id") or "")
    raw = payload.get("payment_intent")
    if not intent_id and isinstance(raw, str) and raw.startswith("pi_"):
        intent_id = raw
    if intent_id.startswith("cs_"):
        intent_id = ""
    intent_id = intent_id or intent_id_from_secret(secret)
    return_url = str(payload.get("confirm_return_url") or payload.get("return_url") or "")
    return intent_id, secret, return_url


def submission_state(payload: Dict[str, Any]) -> str:
    attempt = payload.get("submission_attempt") if isinstance(payload.get("submission_attempt"), dict) else {}
    return str(attempt.get("state") or attempt.get("status") or "").strip().lower()


_FAILURE_KEYS = ("decline_code", "code", "message", "reason", "failure_reason", "failure_code", "type")


def _failure_parts(source: Any) -> list[str]:
    if isinstance(source, str):
        return [source.strip()] if source.strip() else []
    if not isinstance(source, dict):
        return []
    parts: list[str] = []
    for key in _FAILURE_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}={value.strip()}")
    return parts


def submission_failure_detail(payload: Dict[str, Any]) -> str:
    """从失败的 Stripe 响应里尽量找出拒绝原因（decline_code / last_payment_error 等）。"""
    attempt = payload.get("submission_attempt") if isinstance(payload.get("submission_attempt"), dict) else {}
    nested = _intent_object(payload)
    sources = [
        attempt.get("error"),
        attempt.get("last_error"),
        attempt.get("failure"),
        attempt,
        payload.get("last_payment_error"),
        nested.get("last_payment_error"),
        payload.get("error"),
    ]
    seen: list[str] = []
    for source in sources:
        for part in _failure_parts(source):
            if part not in seen:
                seen.append(part)
    return "; ".join(seen[:6])


def checkout_requires_approval(payload: Dict[str, Any]) -> bool:
    return submission_state(payload) in {"requires_approval", "pending_approval"}


def nested_intent_status(payload: Dict[str, Any]) -> str:
    nested = _intent_object(payload)
    return str(nested.get("status") or "").strip().lower()


def payment_page_settled(payload: Dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    state = submission_state(payload)
    pi_status = nested_intent_status(payload)
    if status in {"complete", "completed", "expired"}:
        return True
    if state in {"succeeded", "complete", "completed", "failed", "declined", "canceled", "cancelled"}:
        return True
    if pi_status in {
        "succeeded",
        "processing",
        "requires_action",
        "requires_payment_method",
        "canceled",
        "cancelled",
    }:
        return True
    return False


def _intent_object(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    for key in ("payment_intent", "setup_intent"):
        value = payload.get(key)
        if isinstance(value, dict) and (
            value.get("id") or value.get("client_secret") or value.get("status")
        ):
            return value
    attempt = payload.get("submission_attempt")
    if isinstance(attempt, dict):
        nested = _intent_object(attempt)
        if nested:
            return nested
    elements = payload.get("elements_session")
    if isinstance(elements, dict):
        nested = _intent_object(elements)
        if nested:
            return nested
    return {}


def expected_amount_minor(payload: Any) -> Optional[int]:
    """Stripe payment_pages/confirm 的 expected_amount：应付整数（最小货币单位）。

    init 响应里通常是 ``total_summary.due`` / ``invoice.amount_due``，不是顶层 amount_total。
    """
    if not isinstance(payload, dict):
        return None
    wrappers = (
        payload,
        payload.get("session") if isinstance(payload.get("session"), dict) else None,
        payload.get("checkout_session") if isinstance(payload.get("checkout_session"), dict) else None,
        payload.get("payment_page") if isinstance(payload.get("payment_page"), dict) else None,
    )
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            continue
        found = _expected_amount_from_object(wrapper)
        if found is not None:
            return found
    return None


def _as_minor_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool) or isinstance(value, (dict, list)):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
    text = str(value).strip()
    if not text or "." in text or "," in text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _expected_amount_from_object(payload: Dict[str, Any]) -> Optional[int]:
    summary = payload.get("total_summary")
    if isinstance(summary, dict):
        for key in ("due", "amount_due", "total", "amount"):
            found = _as_minor_int(summary.get(key))
            if found is not None:
                return found
    invoice = payload.get("invoice")
    if isinstance(invoice, dict):
        for key in ("amount_due", "total", "amount_paid"):
            found = _as_minor_int(invoice.get(key))
            if found is not None:
                return found
    for key in ("amount_total", "amount_due", "checkout_amount_minor"):
        found = _as_minor_int(payload.get(key))
        if found is not None:
            return found
    total = payload.get("total")
    if isinstance(total, dict):
        nested = total.get("total") if isinstance(total.get("total"), dict) else None
        if nested:
            found = _as_minor_int(nested.get("minorUnitsAmount") or nested.get("due"))
            if found is not None:
                return found
        for key in ("due", "minorUnitsAmount", "amount", "total"):
            found = _as_minor_int(total.get(key))
            if found is not None:
                return found
    items = payload.get("line_items") or payload.get("lineItems")
    if isinstance(items, list):
        running = 0
        saw = False
        for item in items:
            if not isinstance(item, dict):
                continue
            found = _as_minor_int(item.get("amount") or item.get("amount_total"))
            if found is None:
                continue
            running += found
            saw = True
        if saw:
            return running
    return None


def _stripe_unknown_param(payload: Dict[str, Any]) -> str:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    param = str(error.get("param") or "").strip()
    if param:
        return param
    message = str(error.get("message") or payload.get("message") or "")
    match = re.search(r"unknown parameter[:\s]+['\"]?([A-Za-z0-9_\[\]]+)", message, re.I)
    return match.group(1) if match else ""


def _raise_stripe(payload: Dict[str, Any], status: int) -> None:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or "")
    decline = str(error.get("decline_code") or "")
    message = str(error.get("message") or payload.get("message") or f"Stripe HTTP {status}")
    if "billing country must match" in message.lower():
        raise DomainError(
            ErrorCode.BILLING_COUNTRY_MISMATCH,
            "账单国家必须与出口代理国家一致，请用所选地区的 SID 重试。",
        )
    if "automatic payment methods" in message.lower() and "payment_method_types" in message.lower():
        raise DomainError(
            ErrorCode.PAYMENT_UNKNOWN_STATE,
            "支付方式采集模式和确认接口不一致。请刷新页面后重新创建结账，不要用上一单的输入框。",
        )
    if "expected amount" in message.lower() and "has to be provided" in message.lower():
        raise DomainError(
            ErrorCode.PAYMENT_UNKNOWN_STATE,
            "Stripe 确认缺少应付金额。请重新创建结账后再确认。",
        )
    if status == 402 or code == "card_declined" or decline:
        detail = decline or code or message
        raise DomainError(ErrorCode.PAYMENT_DECLINED, f"发卡行拒绝: {redact_sensitive(detail)}")
    raise DomainError(ErrorCode.PAYMENT_UNKNOWN_STATE, redact_sensitive(message))


_SETI_SECRET = re.compile(r"seti_[A-Za-z0-9]+_secret_[A-Za-z0-9]+")
_SETI_ID = re.compile(r"seti_[A-Za-z0-9]+")


def _walk(payload: Any):
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _walk(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk(item)
    else:
        yield payload


def setup_intent_from_payload(payload: Any) -> tuple[str, str]:
    """从 ChatGPT /payments/payment_method 响应里抽出 seti + client_secret。"""
    secret = ""
    if isinstance(payload, dict):
        nested = payload.get("setup_intent")
        if isinstance(nested, dict):
            nested_id, nested_secret = setup_intent_from_payload(nested)
            if nested_id and nested_secret:
                return nested_id, nested_secret
        for key in ("client_secret", "clientSecret", "setup_intent_client_secret"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("seti_"):
                secret = value
                break
    if not secret:
        for value in _walk(payload):
            if isinstance(value, str) and _SETI_SECRET.search(value):
                secret = _SETI_SECRET.search(value).group(0)
                break
    if not secret:
        return "", ""
    match = _SETI_ID.search(secret)
    setup_id = match.group(0) if match else ""
    if isinstance(payload, dict):
        for key in ("id", "setup_intent_id", "setupIntentId"):
            value = str(payload.get(key) or "")
            if value.startswith("seti_") and "_secret_" not in value:
                setup_id = value
                break
    return setup_id, secret


__all__ = [
    "APP_BASE",
    "ChatGPTClient",
    "CheckoutSession",
    "hosted_checkout_url",
    "stripe_checkout_id",
    "openai_internal_checkout_id",
    "public_checkout_id",
    "clamp_team_seats",
    "checkout_confirm_blocked",
    "checkout_confirm_blocked_advice",
    "checkout_confirm_message",
    "checkout_requires_approval",
    "payment_page_settled",
    "submission_state",
    "nested_intent_status",
    "expected_amount_minor",
    "intent_id_from_secret",
    "jwt_account_id",
    "payment_intent_from_confirm",
    "setup_intent_from_payload",
    "stripe_verify_url",
]
