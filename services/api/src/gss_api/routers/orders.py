"""订单：粘贴 session → 生成结账 → 用浏览器 PaymentMethod 开通。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from gss_contracts import (
    AccountSource,
    BillingMode,
    CardSource,
    Job,
    Mode,
    ModeValidationError,
    Order,
    OrderStatus,
    Plan,
)
from gss_contracts.errors import DomainError, ErrorCode
from gss_core.config import load_settings, use_fake_adapters
from gss_core.countries import is_supported, normalize_country
from gss_core.hosted import TeamHostedClient
from gss_core.proxies import align_proxy_region, configured_proxy, session_proxy
from gss_core.redaction import redact_sensitive
from gss_core.chatgpt import ChatGPTClient, clamp_team_seats
from gss_core.session_token import parse_session_bundle
from gss_core.vault import OrderSecrets, vault
from gss_orchestrator.pipeline import apply_payment_result, assert_deliverable
from gss_payment.adapter import hosted_payment_result

from ..runtime import build_pipeline
from ..schemas import ErrorOut, ModeIn, OrderCreateRequest, OrderOut, OrderPayRequest, SubscriptionOut, TeamPrepareRequest, TeamQuoteRequest
from ..store import store
from .events import notify_order_update

router = APIRouter(prefix="/api", tags=["orders"])
logger = logging.getLogger("gss.orders")
_team_locks: dict[str, asyncio.Lock] = {}


def _to_mode(mode_in: ModeIn) -> Mode:
    return Mode(
        account_source=AccountSource(mode_in.account_source),
        card_source=CardSource(mode_in.card_source),
        billing_mode=BillingMode(mode_in.billing_mode),
        risk_acknowledged=mode_in.risk_acknowledged,
    )


def _to_out(order: Order) -> OrderOut:
    view = store.view(order.id)
    subscription = None
    if view.subscription is not None:
        subscription = SubscriptionOut(
            active=view.subscription.active,
            expires_at=view.subscription.expires_at.isoformat() if view.subscription.expires_at else None,
            channel=view.subscription.channel,
        )
    return OrderOut(
        id=order.id,
        status=str(order.status),
        plan=str(order.plan),
        billing_country=order.billing_country,
        mode=ModeIn(
            account_source=str(order.mode.account_source),
            card_source=str(order.mode.card_source),
            billing_mode=str(order.mode.billing_mode),
            risk_acknowledged=order.mode.risk_acknowledged,
        ),
        checkout_url=view.checkout_url,
        publishable_key=view.publishable_key,
        customer_session_client_secret=view.customer_session_client_secret,
        amount=view.amount if view.amount is not None else (str(order.amount) if order.amount is not None else None),
        currency=view.currency,
        billing=view.billing,
        last_error=view.last_error,
        quote_error=view.quote_error,
        next_action=view.next_action,
        subscription=subscription,
        checkout_kind=view.checkout_kind,
        seat_quantity=view.seat_quantity,
        workspace_name=view.workspace_name,
        promo_code=view.promo_code,
        promo_campaign_id=view.promo_campaign_id,
        price_interval=view.price_interval,
        confirm_return_url=view.confirm_return_url,
    )


def _error(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorOut(code=str(code), message=message).model_dump(),
    )


def _from_domain(exc: DomainError) -> HTTPException:
    status_code = status.HTTP_400_BAD_REQUEST
    if exc.code in {ErrorCode.INVALID_SESSION, ErrorCode.SESSION_EXPIRED}:
        status_code = status.HTTP_401_UNAUTHORIZED
    return _error(status_code, exc.code, exc.message)


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderOut,
    responses={400: {"model": ErrorOut}, 401: {"model": ErrorOut}},
)
async def create_order(
    payload: OrderCreateRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> OrderOut:
    existing = store.find_by_idempotency(idempotency_key)
    if existing is not None:
        return _to_out(existing)

    try:
        plan = Plan(payload.plan)
    except ValueError:
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, f"未知套餐: {payload.plan}")

    try:
        mode = _to_mode(payload.mode)
        mode.validate()
    except ModeValidationError as exc:
        try:
            code = ErrorCode(exc.code)
        except ValueError:
            code = ErrorCode.COMPLIANCE_BLOCKED
        raise _error(status.HTTP_400_BAD_REQUEST, code, exc.message)
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, f"模式非法: {exc}")

    if mode.billing_mode is BillingMode.PROMO and not load_settings().enable_promo_mode:
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, "促销模式尚未启用")

    if mode.account_source is AccountSource.CUSTOMER_SESSION and not payload.session:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_SESSION,
            "请粘贴 ChatGPT session",
        )

    raw_session = (payload.session or "").strip()
    try:
        bundle = parse_session_bundle(raw_session)
    except ValueError as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.INVALID_SESSION, str(exc))
    
    country = normalize_country(payload.billing_country)
    if not is_supported(country):
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, f"不支持的地区: {payload.billing_country}")
    
    # 换 token 与后续提链、支付共用同一个出口（同一 sid），所以只算一次。
    exit_proxy = align_proxy_region(
        session_proxy("checkout", country) or configured_proxy("checkout"),
        country,
    )

    # 只粘贴了 session token：先用本单出口换 accessToken，再按完整 session 继续。
    if not bundle.access_token and bundle.session_token:
        client = ChatGPTClient.from_raw_session(raw_session, proxy=exit_proxy)
        try:
            refreshed = await asyncio.to_thread(client.refresh_session)
        except Exception as exc:
            logger.warning("session token 换取失败: %s", redact_sensitive(str(exc))[:200])
            refreshed = False
        finally:
            client.close()
        if not refreshed or not client.access_token:
            raise _error(
                status.HTTP_401_UNAUTHORIZED,
                ErrorCode.INVALID_SESSION,
                "session token 已失效或无法换取 accessToken，请重新导出 session",
            )
        bundle.access_token = client.access_token
        raw_session = json.dumps({
            "accessToken": client.access_token,
            "sessionToken": client.session_token,
            "deviceId": client.device_id,
            "sessionId": client.oai_session_id,
            "cookies": client.extra_cookies,
        })
        logger.info("已从 session token 换取 accessToken")

    if not bundle.access_token:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.INVALID_SESSION, "JSON 中没有 accessToken")

    seats = 5
    workspace = str(payload.workspace_name or "").strip()
    promo_code = str(payload.promo_code or "").strip()
    promo_campaign_id = str(payload.promo_campaign_id or "").strip()
    interval = "year" if str(payload.price_interval or "").lower() == "year" else "month"
    if plan is Plan.TEAM:
        if payload.seat_quantity is None:
            raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, "Team 需要填写席位，最少 2 人")
        try:
            seats = clamp_team_seats(payload.seat_quantity)
        except ValueError as exc:
            raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, str(exc))
        if not workspace:
            workspace = "Team Workspace"

    order = Order(
        idempotency_key=idempotency_key or "",
        plan=plan,
        billing_country=country,
        mode=mode,
        status=OrderStatus.CREATED,
    )
    store.create_order(order, idempotency_key)
    store.add_job(Job(order_id=order.id, stage="checkout"))
    vault.put(order.id, OrderSecrets(session=raw_session, proxy=exit_proxy or ""))

    pipeline = build_pipeline()
    try:
        checkout = await pipeline.create_checkout(
            session=raw_session,
            plan=plan,
            billing_country=country,
            mode=mode,
            proxy=exit_proxy,
            promo_code=promo_code,
            promo_campaign_id=promo_campaign_id,
            workspace_name=workspace,
            seat_quantity=seats,
            price_interval=interval,
        )
    except DomainError as exc:
        store.update_status(order.id, OrderStatus.REJECTED)
        store.view(order.id).last_error = exc.message
        logger.info(
            "checkout_failed id=%s plan=%s country=%s error=%s",
            order.id,
            plan,
            country,
            exc.message,
        )
        raise _from_domain(exc)

    view = store.view(order.id)
    view.checkout_url = checkout.checkout_url
    view.checkout_session_id = checkout.checkout_session_id
    view.publishable_key = checkout.publishable_key
    view.customer_session_client_secret = checkout.customer_session_client_secret
    view.billing = dict(checkout.billing or {})
    view.amount = str(checkout.amount) if checkout.amount is not None else None
    view.currency = checkout.currency
    view.checkout_kind = checkout.checkout_kind or ("hosted" if plan is Plan.TEAM else "custom")
    view.confirm_return_url = checkout.confirm_return_url or None
    view.promo_code = promo_code or None
    view.promo_campaign_id = promo_campaign_id or None
    if plan is Plan.TEAM:
        view.seat_quantity = seats
        view.workspace_name = workspace
        view.price_interval = interval
    order.amount = checkout.amount
    secrets = vault.get(order.id)
    if secrets is not None:
        secrets.checkout_session_id = checkout.checkout_session_id or ""
        secrets.publishable_key = checkout.publishable_key or ""
        secrets.billing = dict(checkout.billing or {})
        effective_proxy = getattr(checkout, "effective_proxy", None)
        if effective_proxy is not None:
            secrets.proxy = effective_proxy
        vault.put(order.id, secrets)
    store.update_status(order.id, OrderStatus.PENDING_CHECKOUT)
    store.update_status(order.id, OrderStatus.AWAITING_PAYMENT)
    logger.info(
        "checkout_created id=%s plan=%s country=%s amount=%s currency=%s kind=%s seats=%s",
        order.id,
        plan,
        country,
        view.amount,
        view.currency,
        view.checkout_kind,
        view.seat_quantity,
    )

    if payload.payment_method_token:
        return await pay_order(order.id, OrderPayRequest(payment_method_token=payload.payment_method_token))
    return _to_out(store.get_order(order.id))  # type: ignore[arg-type]


async def _mark_delivered(order_id: str) -> None:
    """扣款成功后直接推进到 delivered，并清掉内存里的 session。"""
    current = store.get_order(order_id)
    if current is not None and current.status is OrderStatus.VERIFYING:
        store.update_status(order_id, OrderStatus.ACTIVE)
    current = store.get_order(order_id)
    if current is not None and current.status is OrderStatus.ACTIVE:
        store.update_status(order_id, OrderStatus.DELIVERED)
    store.view(order_id).last_error = None
    store.view(order_id).next_action = None
    vault.drop(order_id)
    await notify_order_update(order_id, OrderStatus.DELIVERED, {"payment_confirmed": True})


def _team_client(secrets: OrderSecrets) -> ChatGPTClient:
    client = ChatGPTClient.from_raw_session(secrets.session, proxy=secrets.proxy or None)
    client.timeout = 30.0
    return client


def _team_quote(view, context: dict) -> None:
    code = context["currency"].upper()
    zero = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
    divisor = 1 if code in zero else 100
    view.amount = str(Decimal(context["amount_minor"]) / divisor)
    view.currency = code
    view.quote_error = None


@router.post("/orders/{order_id}/team/quote", response_model=OrderOut)
async def quote_team(order_id: str, payload: TeamQuoteRequest) -> OrderOut:
    async with _team_locks.setdefault(order_id, asyncio.Lock()):
        order = store.get_order(order_id)
        if order is None or order.plan is not Plan.TEAM:
            raise HTTPException(404, "Team 订单不存在")
        if order.status is not OrderStatus.AWAITING_PAYMENT:
            raise HTTPException(409, "支付已提交，请查询支付状态")
        secrets = vault.get(order_id)
        if secrets is None:
            raise _error(401, ErrorCode.SESSION_EXPIRED, "session 已过期")
        view = store.view(order_id)
        if use_fake_adapters():
            return _to_out(order)
        billing = {k: v.strip() for k, v in payload.billing.model_dump().items()} if payload.billing else None
        if billing:
            billing["country"] = billing["country"].upper()
            if not is_supported(billing["country"]):
                raise HTTPException(400, "不支持的支付账单国家")
        started = time.monotonic()
        client = _team_client(secrets)
        try:
            quote = await asyncio.to_thread(TeamHostedClient(client).quote,
                session_id=secrets.checkout_session_id, key=secrets.publishable_key,
                billing=billing, currency=view.currency or "", browser_locale=payload.browser_locale,
                browser_timezone=payload.browser_timezone)
            _team_quote(view, quote)
            logger.info("team_quote_ok id=%s amount=%s currency=%s elapsed=%.2f",
                        order_id, view.amount, view.currency, time.monotonic() - started)
        except DomainError as exc:
            view.quote_error = exc.message
            logger.warning("team_quote_failed id=%s code=%s elapsed=%.2f error=%s", order_id,
                           exc.code.value, time.monotonic() - started, redact_sensitive(exc.message)[:160])
        except Exception as exc:
            view.quote_error = "读取 Stripe 报价时连接中断，本步骤未提交付款确认"
            logger.warning("team_quote_error id=%s type=%s elapsed=%.2f", order_id, type(exc).__name__,
                           time.monotonic() - started)
        finally:
            client.close()
        return _to_out(order)


@router.post("/orders/{order_id}/team/prepare", tags=["orders"])
async def prepare_team(order_id: str, payload: TeamPrepareRequest) -> dict:
    async with _team_locks.setdefault(order_id, asyncio.Lock()):
        order = store.get_order(order_id)
        if order is None or order.plan is not Plan.TEAM:
            raise HTTPException(404, "Team 订单不存在")
        if order.status is not OrderStatus.AWAITING_PAYMENT:
            raise HTTPException(409, "已提交的订单请查询支付状态，不要重新提交")
        secrets = vault.get(order_id)
        if secrets is None:
            raise _error(401, ErrorCode.SESSION_EXPIRED, "session 已过期")
        billing = {k: v.strip() for k, v in payload.billing.model_dump().items()}
        billing["country"] = billing["country"].upper()
        if not is_supported(billing["country"]):
            raise HTTPException(400, "不支持的支付账单国家")
        if use_fake_adapters():
            context = {"context_id": "fixture-context", "session_id": secrets.checkout_session_id,
                "publishable_key": secrets.publishable_key, "eid": "NA", "amount_minor": 115000,
                "currency": "egp", "billing": billing, "prepared_at": time.time(),
                "checkout_config_id": "fixture-config", "elements_session_id": "elements_fixture",
                "client_session_id": "fixture-client", "guid": "fixture-guid", "muid": "fixture-muid", "sid": "fixture-sid",
                "passive_captcha": {}}
        else:
            started = time.monotonic()
            client = _team_client(secrets)
            try:
                context = await asyncio.to_thread(TeamHostedClient(client).prepare,
                    session_id=secrets.checkout_session_id, key=secrets.publishable_key, billing=billing,
                    currency=store.view(order_id).currency or "", browser_locale=payload.browser_locale,
                    browser_timezone=payload.browser_timezone,
                    on_quote=lambda quote: _team_quote(store.view(order_id), quote))
                logger.info("team_prepare_ok id=%s amount=%s currency=%s elapsed=%.2f",
                            order_id, store.view(order_id).amount, store.view(order_id).currency,
                            time.monotonic() - started)
            except DomainError as exc:
                store.view(order_id).last_error = exc.message
                logger.warning("team_prepare_failed id=%s code=%s elapsed=%.2f confirm_submitted=False error=%s",
                               order_id, exc.code.value, time.monotonic() - started,
                               redact_sensitive(exc.message)[:160])
                raise _from_domain(exc)
            finally:
                client.close()
        secrets.team_context = context
        secrets.billing = billing
        vault.put(order_id, secrets)
        view = store.view(order_id)
        view.billing = billing
        view.last_error = None
        _team_quote(view, context)
        return {"order": _to_out(order).model_dump(), "context": {k: context[k] for k in (
            "context_id", "session_id", "publishable_key", "eid", "amount_minor", "currency",
            "checkout_config_id", "elements_session_id", "client_session_id", "guid", "muid", "sid",
            "passive_captcha", "customer_email") if k in context}}


@router.post("/orders/{order_id}/team/poll", response_model=OrderOut)
async def poll_team(order_id: str) -> OrderOut:
    async with _team_locks.setdefault(order_id, asyncio.Lock()):
        order = store.get_order(order_id)
        if order is None or order.plan is not Plan.TEAM:
            raise HTTPException(404, "Team 订单不存在")
        if order.status in {OrderStatus.DELIVERED, OrderStatus.FAILED, OrderStatus.REJECTED}:
            return _to_out(order)
        secrets = vault.get(order_id)
        if secrets is None:
            raise _error(401, ErrorCode.SESSION_EXPIRED, "session 已过期")
        client = _team_client(secrets)
        try:
            payload = await asyncio.to_thread(TeamHostedClient(client).poll,
                session_id=secrets.checkout_session_id, key=secrets.publishable_key)
        except DomainError as exc:
            raise _from_domain(exc)
        finally:
            client.close()
        result = hosted_payment_result(payload, secrets.checkout_session_id, store.view(order_id).checkout_url or "")
        view = store.view(order_id)
        if result.status.value == "succeeded":
            if order.status in {OrderStatus.AWAITING_PAYMENT, OrderStatus.REQUIRES_ACTION, OrderStatus.UNKNOWN}:
                store.update_status(order_id, OrderStatus.PAYING)
            if order.status is OrderStatus.PAYING:
                store.update_status(order_id, OrderStatus.VERIFYING)
            view.next_action = None
            await _mark_delivered(order_id)
        elif result.status.value == "declined":
            store.update_status(order_id, OrderStatus.FAILED)
            view.last_error = result.message
            view.next_action = None
            await notify_order_update(order_id, OrderStatus.FAILED)
        elif result.status.value == "requires_action":
            if order.status is OrderStatus.AWAITING_PAYMENT:
                store.update_status(order_id, OrderStatus.PAYING)
            store.update_status(order_id, OrderStatus.REQUIRES_ACTION)
            view.next_action = result.next_action
            view.last_error = result.message
        # Pending poll responses must not erase an earlier challenge/client_secret.
        return _to_out(order)


@router.post(
    "/orders/{order_id}/pay",
    response_model=OrderOut,
    responses={400: {"model": ErrorOut}, 401: {"model": ErrorOut}, 404: {"model": ErrorOut}},
)
async def pay_order(order_id: str, payload: OrderPayRequest) -> OrderOut:
    async with _team_locks.setdefault(order_id, asyncio.Lock()):
        return await _pay_order(order_id, payload)


async def _pay_order(order_id: str, payload: OrderPayRequest) -> OrderOut:
    order = store.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    if order.status in {OrderStatus.DELIVERED, OrderStatus.ACTIVE}:
        return _to_out(order)
    if order.status is not OrderStatus.AWAITING_PAYMENT:
        raise HTTPException(409, "支付已提交，请查询状态，不要重复确认")
    secrets = vault.get(order_id)
    if secrets is None:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.SESSION_EXPIRED, "session 已过期，请重新提交")

    if order.plan is Plan.TEAM and not use_fake_adapters():
        context = secrets.team_context
        address = {k: v.strip() for k, v in payload.billing.model_dump().items()} if payload.billing else dict(secrets.billing)
        address["country"] = address.get("country", "").upper()
        address.setdefault("email", "")
        if not context or context.get("context_id") != payload.team_context_id:
            raise HTTPException(409, "Team 会话上下文不匹配，请重新初始化")
        if time.time() - context["prepared_at"] > 600 or address != context["billing"]:
            raise HTTPException(409, "Team 账单或会话已变更，请重新初始化")
        # Server-side card submission acquires its own pm_ and may run without a browser captcha token.
        if (payload.card is None and context.get("passive_captcha", {}).get("site_key")
                and not payload.passive_captcha_token):
            raise HTTPException(400, "请先完成当前会话的 Stripe 验证")

        if payload.card is not None:
            if payload.payment_method_token:
                raise HTTPException(400, "卡号与 payment_method 只能二选一")
            started = time.monotonic()
            client = _team_client(secrets)
            try:
                pm_id = await asyncio.to_thread(
                    TeamHostedClient(client).tokenize,
                    card=payload.card.model_dump(), billing=address,
                    publishable_key=secrets.publishable_key, session_id=secrets.checkout_session_id,
                    device={"guid": context.get("guid", ""), "muid": context.get("muid", ""),
                            "sid": context.get("sid", ""),
                            "client_session_id": context.get("client_session_id", "")},
                    captcha_token=payload.passive_captcha_token or "",
                    time_on_page_ms=int((time.time() - float(context.get("prepared_at") or time.time())) * 1000),
                )
                logger.info("team_tokenize_ok id=%s elapsed=%.2f", order_id, time.monotonic() - started)
            except DomainError as exc:
                logger.warning("team_tokenize_failed id=%s code=%s elapsed=%.2f error=%s", order_id,
                               exc.code.value, time.monotonic() - started,
                               redact_sensitive(exc.message)[:160])
                raise _from_domain(exc)
            finally:
                client.close()
            payload = payload.model_copy(update={"payment_method_token": pm_id})

    if payload.billing is not None:
        custom = {k: v.strip() for k, v in payload.billing.model_dump().items()}
        custom["country"] = custom["country"].upper()
        # Team 的 order.billing_country 是创建结账的地区（决定币种）；
        # custom.country 是支付账单国家，独立用于 PaymentMethod 和 Stripe tax_region。
        if order.plan is Plan.TEAM:
            if not is_supported(custom["country"]):
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    ErrorCode.BILLING_COUNTRY_MISMATCH,
                    f"不支持的账单国家: {custom['country']}",
                )
        elif custom["country"] != order.billing_country:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.BILLING_COUNTRY_MISMATCH,
                f"账单地址国家 {custom['country']} 与订单地区 {order.billing_country} 不一致",
            )
        secrets.billing = custom
        vault.put(order_id, secrets)

    view = store.view(order_id)
    if payload.billing is not None:
        view.billing = dict(secrets.billing)
    pipeline = build_pipeline()
    store.update_status(order_id, OrderStatus.PAYING)
    try:
        payment = await pipeline.pay(
            checkout_url=view.checkout_url or "",
            country=order.billing_country,
            mode=order.mode,
            payment_method_token=payload.payment_method_token,
            session=secrets.session,
            checkout_session_id=view.checkout_session_id or secrets.checkout_session_id,
            publishable_key=view.publishable_key or secrets.publishable_key,
            checkout_proxy=secrets.proxy or None,
            approve_proxy=secrets.proxy or None,
            billing=secrets.billing or None,
            plan=str(order.plan), team_context=secrets.team_context,
            passive_captcha_token=payload.passive_captcha_token, rv_timestamp=payload.rv_timestamp,
        )
    except DomainError as exc:
        uncertain = order.plan is Plan.TEAM and exc.code is ErrorCode.PAYMENT_UNKNOWN_STATE
        failed_status = OrderStatus.UNKNOWN if uncertain else OrderStatus.FAILED
        store.update_status(order_id, failed_status)
        view.last_error = exc.message
        logger.info(
            "pay_failed id=%s country=%s error=%s",
            order_id,
            order.billing_country,
            exc.message,
        )
        # SSE 通知：支付失败
        await notify_order_update(order_id, failed_status, {"error": exc.message})
        raise _from_domain(exc)

    new_status = apply_payment_result(OrderStatus.PAYING, payment.status)
    store.update_status(order_id, new_status)
    view.next_action = payment.next_action
    view.last_error = None if payment.status.value == "succeeded" else payment.message
    logger.info(
        "pay_finished id=%s country=%s payment=%s order=%s error=%s",
        order_id,
        order.billing_country,
        payment.status,
        new_status,
        view.last_error or "",
    )
    
    # SSE 通知：支付状态更新
    await notify_order_update(order_id, new_status, {"payment_status": payment.status.value})

    if new_status is OrderStatus.VERIFYING and order.plan is Plan.TEAM:
        await _mark_delivered(order_id)
    elif new_status is OrderStatus.VERIFYING:
        # 业务规则：扣款成功即视为开通成功。订阅查询只作为附带信息，失败或尚未生效都不影响结果。
        try:
            info = await pipeline.verify(session=secrets.session)
            view.subscription = info
        except DomainError as exc:
            logger.warning("verify_after_pay_failed id=%s error=%s", order_id, redact_sensitive(exc.message)[:200])
        await _mark_delivered(order_id)
    return _to_out(store.get_order(order_id))  # type: ignore[arg-type]


@router.post(
    "/orders/{order_id}/verify",
    response_model=OrderOut,
    responses={401: {"model": ErrorOut}, 404: {"model": ErrorOut}},
)
async def verify_order(order_id: str, paid: bool = False) -> OrderOut:
    order = store.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    if order.plan is Plan.TEAM and not use_fake_adapters():
        return await poll_team(order_id)
    secrets = vault.get(order_id)
    if secrets is None:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.SESSION_EXPIRED, "session 已过期，请重新提交")
    view = store.view(order_id)
    pipeline = build_pipeline()
    current = store.get_order(order_id)
    if current is not None and current.status in {OrderStatus.AWAITING_PAYMENT, OrderStatus.REQUIRES_ACTION, OrderStatus.UNKNOWN}:
        # 3DS 验证完成（或不确定态复查）后从这里继续往 verifying 推进。
        store.update_status(order_id, OrderStatus.PAYING)
    current = store.get_order(order_id)
    if current is not None and current.status is OrderStatus.PAYING:
        store.update_status(order_id, OrderStatus.VERIFYING)
    try:
        info = await pipeline.verify(session=secrets.session)
    except DomainError as exc:
        if exc.code in {ErrorCode.INVALID_SESSION, ErrorCode.SESSION_EXPIRED}:
            raise _from_domain(exc)
        # 上游查询暂时出错：保持当前状态返回，由前端稍后重查，不把已支付订单打成失败。
        logger.warning("verify_failed id=%s error=%s", order_id, redact_sensitive(exc.message)[:200])
        if paid:
            await _mark_delivered(order_id)
            return _to_out(store.get_order(order_id))  # type: ignore[arg-type]
        view.last_error = f"订阅状态查询失败，稍后会自动重试：{exc.message[:120]}"
        return _to_out(store.get_order(order_id))  # type: ignore[arg-type]
    view.subscription = info
    if info.active:
        store.update_status(order_id, OrderStatus.ACTIVE)
        assert_deliverable(OrderStatus.ACTIVE, info)
        store.update_status(order_id, OrderStatus.DELIVERED)
        view.last_error = None
        vault.drop(order_id)
        # SSE 通知：订阅激活并交付
        await notify_order_update(order_id, OrderStatus.DELIVERED, {"subscription_active": True})
    elif paid:
        await _mark_delivered(order_id)
    else:
        view.last_error = "订阅尚未生效。若是 Team 长链,请先打开链接完成支付再查询。"
        # SSE 通知：验证失败
        current_status = store.get_order(order_id)
        if current_status:
            await notify_order_update(order_id, current_status.status, {"subscription_active": False})
    return _to_out(store.get_order(order_id))  # type: ignore[arg-type]


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut,
    responses={404: {"model": ErrorOut}},
)
async def get_order(order_id: str) -> OrderOut:
    order = store.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    return _to_out(order)
