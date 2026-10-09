"""共享底座包：脱敏日志、配置加载、传输工具。"""

from __future__ import annotations

from .redaction import (
    MASK,
    RedactingFilter,
    install_logging_filter,
    redact,
    redact_mapping,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "MASK",
    "redact",
    "redact_mapping",
    "RedactingFilter",
    "install_logging_filter",
]
