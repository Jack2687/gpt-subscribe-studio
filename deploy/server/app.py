"""自有服务器入口：同源提供订单 API 与编译后的前端。"""

import os

from fastapi.staticfiles import StaticFiles

from dcp_api.main import create_app
from dcp_api.test_access import TestAccessMiddleware

app = create_app()
app.add_middleware(
    TestAccessMiddleware,
    credentials_file=os.environ["DCP_AUTH_FILE"],
    login_file="/app/login.html",
    origin=os.environ.get("DCP_PUBLIC_ORIGIN", ""),
)
app.mount("/", StaticFiles(directory="/app/web", html=True), name="web")
