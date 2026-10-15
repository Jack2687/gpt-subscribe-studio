"""账号能力服务。"""

from __future__ import annotations

from .adapter import AccountAdapterBase, FakeAccountAdapter, UpstreamAccountAdapter

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AccountAdapterBase",
    "UpstreamAccountAdapter",
    "FakeAccountAdapter",
]
