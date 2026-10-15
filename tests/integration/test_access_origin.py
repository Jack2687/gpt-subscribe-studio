from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gss_api.test_access import TestAccessMiddleware


def _client(tmp_path: Path, origin: str = "") -> TestClient:
    creds = tmp_path / "auth.json"
    creds.write_text(json.dumps({"password": "pw"}))
    login = tmp_path / "login.html"
    login.write_text("<html>{{ERROR_HIDDEN}}{{INVALID}}</html>")
    app = FastAPI()
    app.add_middleware(
        TestAccessMiddleware, credentials_file=str(creds), login_file=str(login), origin=origin
    )
    return TestClient(app, base_url="https://pay.example.org")


def test_same_origin_is_accepted_without_configured_domain(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/login", data={"password": "wrong"}, headers={"Origin": "https://pay.example.org"})
    assert resp.status_code != 403


def test_foreign_origin_is_rejected_without_configured_domain(tmp_path: Path) -> None:
    client = _client(tmp_path)
    resp = client.post("/login", data={"password": "pw"}, headers={"Origin": "https://evil.example.net"})
    assert resp.status_code == 403


def test_explicit_origin_overrides_host_check(tmp_path: Path) -> None:
    client = _client(tmp_path, origin="https://app.example.com")
    ok = client.post("/login", data={"password": "wrong"}, headers={"Origin": "https://app.example.com"})
    bad = client.post("/login", data={"password": "wrong"}, headers={"Origin": "https://pay.example.org"})
    assert ok.status_code != 403
    assert bad.status_code == 403
