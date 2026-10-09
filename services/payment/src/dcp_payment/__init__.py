"""卡绑定与支付执行能力服务。"""

from __future__ import annotations

from .adapter import FakePaymentAdapter, PaymentAdapterBase, UpstreamPaymentAdapter

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "PaymentAdapterBase",
    "UpstreamPaymentAdapter",
    "FakePaymentAdapter",
]
