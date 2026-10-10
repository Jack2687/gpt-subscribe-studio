"""订单：粘贴 session → 生成结账 → 用浏览器 PaymentMethod 开通。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from dcp_contracts import (
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
from dcp_contracts.errors import DomainError, ErrorCode
from dcp_core.config import load_settings
from dcp_core.countries import is_supported, normalize_country
from dcp_core.proxies import align_proxy_region, configured_proxy, session_proxy
from dcp_core.chatgpt import clamp_team_seats
from dcp_core.session_token import parse_session_bundle
from dcp_core.vault import OrderSecrets, vault
from dcp_orchestrator.pipeline import apply_payment_result, assert_deliverable

from ..runtime import build_pipeline
from ..schemas import ErrorOut, ModeIn, OrderCreateRequest, OrderOut, OrderPayRequest, SubscriptionOut
from ..store import store

router = APIRouter(prefix="/api", tags=["orders"])
logger = logging.getLogger("dcp.orders")


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
        next_action=view.next_action,
        subscription=subscription,
        checkout_kind=view.checkout_kind,
        seat_quantity=view.seat_quantity,
        workspace_name=view.workspace_name,
        promo_code=view.promo_code,
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
    if not bundle.access_token:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.INVALID_SESSION, "JSON 中没有 accessToken")

    country = normalize_country(payload.billing_country)
    if not is_supported(country):
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, f"不支持的地区: {payload.billing_country}")
    seats = 5
    workspace = str(payload.workspace_name or "").strip()
    promo_code = str(payload.promo_code or "").strip()
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
    exit_proxy = align_proxy_region(
        session_proxy("checkout", country) or configured_proxy("checkout"),
        country,
    )

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
    if plan is Plan.TEAM:
        view.seat_quantity = seats
        view.workspace_name = workspace
        view.promo_code = promo_code or None
        view.price_interval = interval
    order.amount = checkout.amount
    secrets = vault.get(order.id)
    if secrets is not None:
        secrets.checkout_session_id = checkout.checkout_session_id or ""
        secrets.publishable_key = checkout.publishable_key or ""
        secrets.billing = dict(checkout.billing or {})
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


@router.post(
    "/orders/{order_id}/pay",
    response_model=OrderOut,
    responses={400: {"model": ErrorOut}, 401: {"model": ErrorOut}, 404: {"model": ErrorOut}},
)
async def pay_order(order_id: str, payload: OrderPayRequest) -> OrderOut:
    order = store.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    secrets = vault.get(order_id)
    if secrets is None:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.SESSION_EXPIRED, "session 已过期，请重新提交")

    if payload.billing is not None:
        custom = {k: v.strip() for k, v in payload.billing.model_dump().items()}
        custom["country"] = custom["country"].upper()
        if custom["country"] != order.billing_country:
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
            plan=str(order.plan),
        )
    except DomainError as exc:
        store.update_status(order_id, OrderStatus.FAILED)
        view.last_error = exc.message
        logger.info(
            "pay_failed id=%s country=%s error=%s",
            order_id,
            order.billing_country,
            exc.message,
        )
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

    if new_status is OrderStatus.VERIFYING:
        info = await pipeline.verify(session=secrets.session)
        view.subscription = info
        if info.active:
            store.update_status(order_id, OrderStatus.ACTIVE)
            assert_deliverable(OrderStatus.ACTIVE, info)
            store.update_status(order_id, OrderStatus.DELIVERED)
            vault.drop(order_id)
        else:
            view.last_error = "支付已提交，但订阅尚未生效，请稍后刷新"
    return _to_out(store.get_order(order_id))  # type: ignore[arg-type]


@router.post(
    "/orders/{order_id}/verify",
    response_model=OrderOut,
    responses={401: {"model": ErrorOut}, 404: {"model": ErrorOut}},
)
async def verify_order(order_id: str) -> OrderOut:
    order = store.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    secrets = vault.get(order_id)
    if secrets is None:
        raise _error(status.HTTP_401_UNAUTHORIZED, ErrorCode.SESSION_EXPIRED, "session 已过期，请重新提交")
    view = store.view(order_id)
    pipeline = build_pipeline()
    current = store.get_order(order_id)
    if current is not None and current.status is OrderStatus.AWAITING_PAYMENT:
        store.update_status(order_id, OrderStatus.PAYING)
    current = store.get_order(order_id)
    if current is not None and current.status is OrderStatus.PAYING:
        store.update_status(order_id, OrderStatus.VERIFYING)
    info = await pipeline.verify(session=secrets.session)
    view.subscription = info
    if info.active:
        store.update_status(order_id, OrderStatus.ACTIVE)
        assert_deliverable(OrderStatus.ACTIVE, info)
        store.update_status(order_id, OrderStatus.DELIVERED)
        view.last_error = None
        vault.drop(order_id)
    else:
        view.last_error = "订阅尚未生效。若是 Team 长链，请先打开链接完成支付再查询。"
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
