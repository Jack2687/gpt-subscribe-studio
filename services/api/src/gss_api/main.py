"""FastAPI 应用入口。默认只监听回环地址。"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from gss_core import install_logging_filter
from gss_core.config import load_settings, missing_upstreams, use_fake_adapters
from gss_core.proxies import GatewayStore

from .routers import orders, proxies

__version__ = "0.1.0"


def _ensure_info_logging() -> None:
    gss = logging.getLogger("gss")
    gss.setLevel(logging.INFO)
    if not gss.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        gss.addHandler(handler)
    gss.propagate = False


def create_app() -> FastAPI:
    install_logging_filter()
    _ensure_info_logging()
    install_logging_filter(logging.getLogger("gss"))
    settings = load_settings()

    app = FastAPI(
        title="gpt-subscribe-studio API",
        version=__version__,
        description="独立的 ChatGPT 订阅开通工具：粘贴 session，浏览器填卡。",
    )
    app.include_router(orders.router)
    app.state.gateway_store = GatewayStore()
    app.include_router(proxies.router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "promo_enabled": settings.enable_promo_mode,
            "fake_adapters": use_fake_adapters(),
            "missing_upstreams": missing_upstreams(settings),
        }

    return app


app = create_app()
