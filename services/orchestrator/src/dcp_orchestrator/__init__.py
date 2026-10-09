"""订单编排服务：显式状态机推进、阶段路由、断点续跑。"""

from __future__ import annotations

from .pipeline import (
    PAYMENT_STATUS_TO_ORDER,
    OrderPipeline,
    PipelineDeps,
    assert_deliverable,
    next_order_status,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "PipelineDeps",
    "OrderPipeline",
    "PAYMENT_STATUS_TO_ORDER",
    "next_order_status",
    "assert_deliverable",
]
