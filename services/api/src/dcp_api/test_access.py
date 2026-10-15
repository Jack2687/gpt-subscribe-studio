"""自有服务器测试入口：单密码表单与签名会话 cookie。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "__Host-dcp_session"
SESSION_SECONDS = 12 * 60 * 60


class TestAccessMiddleware(BaseHTTPMiddleware):
    __test__ = False

    def __init__(self, app, *, credentials_file: str, login_file: str, origin: str = ""):
        super().__init__(app)
        password = json.loads(Path(credentials_file).read_text())["password"]
        if not isinstance(password, str) or not password:
            raise ValueError("测试入口必须配置非空密码")
        self.password_hash = hashlib.sha256(password.encode()).digest()
        self.signing_key = hmac.digest(self.password_hash, b"dcp-test-session-v1", "sha256")
        self.login_html = Path(login_file).read_text()
        # 为空时按「Origin 与请求 Host 同源」校验，部署到任何域名都不用改代码。
        self.origin = origin.strip().rstrip("/")

    def _same_origin(self, origin: str, request) -> bool:
        if self.origin:
            return origin == self.origin
        return urlsplit(origin).netloc == request.headers.get("host", "")

    def issue_session(self) -> str:
        payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(self.signing_key, payload.encode(), "sha256").hexdigest()
        return payload + "." + signature

    def valid_session(self, token: str) -> bool:
        if len(token) > 256:
            return False
        try:
            expiry, nonce, signature = token.split(".")
            expected = hmac.new(self.signing_key, f"{expiry}.{nonce}".encode(), "sha256").hexdigest()
            return int(expiry) > time.time() and hmac.compare_digest(signature.encode(), expected.encode())
        except (ValueError, UnicodeError):
            return False

    def login_page(self, error: bool = False):
        html = self.login_html.replace("{{ERROR_HIDDEN}}", "" if error else "hidden")
        html = html.replace("{{INVALID}}", "true" if error else "false")
        return HTMLResponse(
            html,
            status_code=401 if error else 200,
            headers={"Cache-Control": "no-store"},
        )

    async def dispatch(self, request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and not self._same_origin(origin, request):
                return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
        authenticated = self.valid_session(request.cookies.get(COOKIE, ""))
        if request.url.path == "/login":
            if request.method == "GET":
                return RedirectResponse("/", 303) if authenticated else self.login_page()
            if request.method == "POST":
                if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
                    return JSONResponse({"detail": "登录表单格式不正确"}, status_code=415)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 4096:
                        return JSONResponse({"detail": "登录内容过长"}, status_code=413)
                try:
                    password = parse_qs(body.decode("utf-8")).get("password", [""])[0]
                except UnicodeError:
                    return self.login_page(error=True)
                if not hmac.compare_digest(hashlib.sha256(password.encode()).digest(), self.password_hash):
                    return self.login_page(error=True)
                response = RedirectResponse("/", 303, headers={"Cache-Control": "no-store"})
                response.set_cookie(
                    COOKIE,
                    self.issue_session(),
                    max_age=SESSION_SECONDS,
                    secure=True,
                    httponly=True,
                    samesite="strict",
                    path="/",
                )
                return response
            return JSONResponse({"detail": "不支持该方法"}, status_code=405)
        if request.url.path == "/logout" and request.method == "POST":
            response = RedirectResponse("/login", 303)
            response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
            return response
        if not authenticated:
            if request.url.path.startswith("/api/") or request.method not in {"GET", "HEAD"}:
                return JSONResponse(
                    {"detail": "请先输入访问密码"},
                    status_code=401,
                    headers={"Cache-Control": "no-store"},
                )
            return RedirectResponse("/login", 303, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
