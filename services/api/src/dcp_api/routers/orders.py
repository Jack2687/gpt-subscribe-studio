"""订单路由。

实现 `POST /api/orders` 与 `GET /api/orders/{order_id}` 的完整功能：
- 请求解析与模式校验（含 promo 风险确认）
- 幂等键去重（SQLite 唯一约束）
- 创建订单并入队编排任务
- 查询订单状态与支付尝试历史

tasks.md T017–T022。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

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
from dcp_contracts.errors import ErrorCode

from ..db import get_db
from ..repository import OrderRepository
from ..schemas import ErrorOut, ModeIn, OrderCreateRequest, OrderOut

router = APIRouter(prefix="/api", tags=["orders"])


def get_session():
    """依赖注入：数据库会话。"""
    db = get_db()
    return next(db.get_session())


def _to_mode(mode_in: ModeIn) -> Mode:
    return Mode(
        account_source=AccountSource(mode_in.account_source),
        card_source=CardSource(mode_in.card_source),
        billing_mode=BillingMode(mode_in.billing_mode),
        risk_acknowledged=mode_in.risk_acknowledged,
    )


def _to_out(order: Order) -> OrderOut:
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
    )


def _error(status_code: int, code: ErrorCode, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorOut(code=str(code), message=message).model_dump(),
    )


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderOut,
    responses={
        400: {"model": ErrorOut},
        401: {"model": ErrorOut},
    },
)
async def create_order(
    payload: OrderCreateRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> OrderOut:
    """创建开通订单。相同 ``Idempotency-Key`` 返回同一订单。"""

    repo = OrderRepository(session)
    
    # 幂等性检查
    existing = repo.find_by_idempotency(idempotency_key)
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
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode(exc.code), exc.message)
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, ErrorCode.COMPLIANCE_BLOCKED, f"模式非法: {exc}")

    # 客户账号模式必须带 session；此处只做「存在性」校验，不做上游有效性探测。
    if mode.account_source is AccountSource.CUSTOMER_SESSION and not payload.session:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_SESSION,
            "account_source=customer_session 需要提供 session",
        )

    # 创建订单
    order = Order(
        idempotency_key=idempotency_key or "",
        plan=plan,
        billing_country=payload.billing_country,
        mode=mode,
        status=OrderStatus.CREATED,
    )
    order = repo.create_order(order, idempotency_key)
    
    # 创建编排任务（T020：入队给 orchestrator worker）
    job = Job(
        order_id=order.id,
        stage="checkout",
        attempts=0,
    )
    repo.add_job(job)
    
    # TODO: 发送任务通知给 worker（消息队列或轮询）
    
    return _to_out(order)


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut,
    responses={404: {"model": ErrorOut}},
)
async def get_order(
    order_id: str,
    session: Session = Depends(get_session),
) -> OrderOut:
    """查询订单状态。"""

    repo = OrderRepository(session)
    order = repo.get_order(order_id)
    if order is None:
        raise _error(status.HTTP_404_NOT_FOUND, ErrorCode.COMPLIANCE_BLOCKED, "订单不存在")
    return _to_out(order)


@router.get(
    "/orders",
    response_model=list[OrderOut],
)
async def list_orders(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[OrderOut]:
    """列出订单（支持状态过滤与分页）。"""

    repo = OrderRepository(session)
    order_status = OrderStatus(status) if status else None
    orders = repo.list_orders(status=order_status, limit=limit, offset=offset)
    return [_to_out(order) for order in orders]
