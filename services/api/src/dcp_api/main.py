"""FastAPI 应用入口。

    uvicorn dcp_api.main:app --host 127.0.0.1 --port 8080

默认只监听回环地址（宪法「技术与安全约束」）。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from dcp_core import install_logging_filter
from dcp_core.config import load_settings, missing_upstreams

from .db import init_db
from .routers import orders

__version__ = "0.1.0"


def create_app() -> FastAPI:
    """构造应用。默认开启脱敏日志过滤器并初始化数据库。"""

    install_logging_filter()
    settings = load_settings()

    # 初始化数据库
    db_path = os.environ.get("DCP_DB_PATH", "data/dcp.db")
    db_url = f"sqlite:///{db_path}"
    
    # 确保数据目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    init_db(db_url)

    app = FastAPI(
        title="DirectCard Protocol API",
        version=__version__,
        description="自托管的 ChatGPT 订阅代开编排平台 API",
    )
    app.include_router(orders.router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        missing = missing_upstreams(settings)
        return {
            "status": "ok",
            "version": __version__,
            "promo_enabled": settings.enable_promo_mode,
            "db_path": db_path,
            # 未配置上游时给出提示，但不阻断启动（便于离线开发）。
            "missing_upstreams": missing,
        }

    return app


app = create_app()
