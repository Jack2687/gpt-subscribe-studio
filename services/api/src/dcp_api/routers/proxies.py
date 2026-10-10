"""出口代理配置。提链与支付分阶段，互不覆盖。"""

from __future__ import annotations

import ipaddress
import time

import httpx
from fastapi import APIRouter, HTTPException, Request

from dcp_core.proxies import ROLES, GatewayStore

router = APIRouter(prefix="/api/settings/proxies", tags=["settings"])


def store(request: Request) -> GatewayStore:
    return request.app.state.gateway_store


@router.get("")
async def get_proxies(request: Request):
    try:
        return {role: store(request).get(role).public() for role in ROLES}
    except (OSError, ValueError, TypeError):
        raise HTTPException(500, "代理配置读取失败")


@router.put("/{role}")
async def save_proxy(role: str, request: Request):
    if role not in ROLES:
        raise HTTPException(404, "未知代理阶段")
    try:
        values = await request.json()
        gateway = store(request).save(role, values)
        return gateway.public()
    except ValueError as exc:
        message = str(exc) if type(exc) is ValueError else "代理配置格式不正确"
        raise HTTPException(400, message)
    except (TypeError, OSError):
        raise HTTPException(400, "代理配置保存失败，请检查参数与文件权限")


async def probe_gateway(proxy_url: str) -> dict:
    start = time.perf_counter()
    async with httpx.AsyncClient(
        proxy=proxy_url, timeout=12.0, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.get("https://api64.ipify.org?format=json")
        response.raise_for_status()
        ip = str(ipaddress.ip_address(response.json()["ip"]))
    return {"ip": ip, "elapsed_ms": round((time.perf_counter() - start) * 1000)}


@router.post("/{role}/test")
async def test_proxy(role: str, request: Request):
    if role not in ROLES:
        raise HTTPException(404, "未知代理阶段")
    try:
        gateway = store(request).get(role)
        proxy_url = gateway.proxy_url()
        if proxy_url is None:
            raise HTTPException(400, "请先启用并保存该阶段代理")
        result = await probe_gateway(proxy_url)
        return {"role": role, "region": gateway.region, "sid": gateway.sid, **result}
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
        raise HTTPException(502, "代理连接失败，请检查网关、账号密码和供应商白名单后重试")
