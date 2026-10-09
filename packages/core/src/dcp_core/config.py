"""配置加载：环境变量 + 分片配置 + 应急覆盖（对应 tasks.md T009）。

遵循上游 `GPT-Register-Tool` 的做法：**已有分片时不合并旧 config.json**，
并支持用环境变量应急覆盖上游轮换的 key / SDK 版本，无需改代码。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 分片文件 → 归属的顶层键（上游约定）。
SHARD_FILES = ("proxy.json", "runtime.json", "payment.json")

#: 应急环境变量覆盖（见 docs/architecture.md）。
ENV_STRIPE_PUBLISHABLE_KEY = "PP_STRIPE_PUBLISHABLE_KEY"
ENV_SENTINEL_VERSION = "OPENAI_SENTINEL_VERSION"
ENV_SENTINEL_DISABLE_QUICKJS = "OPENAI_SENTINEL_DISABLE_QUICKJS"


@dataclass
class Settings:
    """平台运行配置。**不含任何凭据明文**，凭据一律走临时文件或环境变量注入。"""

    data_dir: Path = field(default_factory=lambda: Path("runtime"))
    db_path: Path = field(default_factory=lambda: Path("runtime/app.db"))
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080
    enable_promo_mode: bool = False
    upstream_paths: Dict[str, str] = field(default_factory=dict)
    emergency_overrides: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


def _load_shards(config_dir: Path) -> Dict[str, Any]:
    """按分片优先级加载配置；已存在分片时忽略旧 config.json。"""

    merged: Dict[str, Any] = {}
    found_any = False
    for name in SHARD_FILES:
        path = config_dir / name
        if path.is_file():
            found_any = True
            with path.open("r", encoding="utf-8") as fh:
                merged.update(json.load(fh))
    if not found_any:
        legacy = config_dir / "config.json"
        if legacy.is_file():
            with legacy.open("r", encoding="utf-8") as fh:
                merged.update(json.load(fh))
    return merged


def _emergency_overrides(env: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in (
        ENV_STRIPE_PUBLISHABLE_KEY,
        ENV_SENTINEL_VERSION,
        ENV_SENTINEL_DISABLE_QUICKJS,
    ):
        if key in env and env[key]:
            out[key] = env[key]
    return out


def load_settings(
    config_dir: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> Settings:
    """加载配置。``env`` 便于测试注入。"""

    environ = env if env is not None else os.environ
    config_dir = config_dir or Path(environ.get("DCP_CONFIG_DIR", "config"))

    settings = Settings(
        data_dir=Path(environ.get("DCP_DATA_DIR", "runtime")),
        bind_host=environ.get("DCP_BIND_HOST", "127.0.0.1"),
        bind_port=int(environ.get("DCP_BIND_PORT", "8080")),
        enable_promo_mode=environ.get("DCP_ENABLE_PROMO", "").lower()
        in {"1", "true", "yes"},
        emergency_overrides=_emergency_overrides(environ),
    )
    settings.db_path = settings.data_dir / "app.db"

    if config_dir.is_dir():
        settings.extra = _load_shards(config_dir)

    upstream = {
        key: value
        for key, value in environ.items()
        if key.startswith("UPSTREAM_") and value
    }
    settings.upstream_paths = upstream
    return settings


def missing_upstreams(settings: Settings) -> List[str]:
    """返回尚未配置的上游引用名，供启动自检提示。"""

    required = {
        "UPSTREAM_GPT_REGISTER_TOOL_PATH": "GPT-Register-Tool（checkout / account）",
        "UPSTREAM_ZKKY_PATH": "zkky（payment）",
    }
    return [desc for key, desc in required.items() if key not in settings.upstream_paths]


__all__ = [
    "Settings",
    "load_settings",
    "missing_upstreams",
    "SHARD_FILES",
    "ENV_STRIPE_PUBLISHABLE_KEY",
    "ENV_SENTINEL_VERSION",
    "ENV_SENTINEL_DISABLE_QUICKJS",
]
