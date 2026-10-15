from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gss_api.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GSS_PROXY_CONFIG", str(tmp_path / "proxy-gateways.json"))
    return TestClient(create_app())


RAW = "http://acct-region-US-sid-AAAA1111:topsecret@gw.example.com:3010"


def test_parse_previews_without_saving(client: TestClient) -> None:
    resp = client.post("/api/settings/proxies/parse", json={"raw": RAW})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["host"] == "gw.example.com" and body["region"] == "US" and body["sid"] == "AAAA1111"
    assert body["has_region_param"] is True
    assert "topsecret" not in resp.text
    assert client.get("/api/settings/proxies").json()["checkout"]["host"] == ""


def test_save_applies_to_both_stages_and_hides_password(client: TestClient) -> None:
    resp = client.put("/api/settings/proxies", json={"raw": RAW, "enabled": True})
    assert resp.status_code == 200, resp.text
    assert "topsecret" not in resp.text
    saved = client.get("/api/settings/proxies").json()
    for role in ("checkout", "approve"):
        assert saved[role]["host"] == "gw.example.com"
        assert saved[role]["enabled"] is True
        assert saved[role]["has_password"] is True
    assert "topsecret" not in client.get("/api/settings/proxies").text


def test_save_replaces_previous_region_instead_of_keeping_it(client: TestClient) -> None:
    client.put("/api/settings/proxies", json={"raw": RAW})
    client.put("/api/settings/proxies", json={"raw": "http://acct-region-JP-sid-BBBB2222:pw@gw.example.com:3010"})
    saved = client.get("/api/settings/proxies").json()["checkout"]
    assert (saved["region"], saved["sid"]) == ("JP", "BBBB2222")


def test_bad_input_is_400(client: TestClient) -> None:
    assert client.post("/api/settings/proxies/parse", json={"raw": "nonsense"}).status_code == 400
    assert client.put("/api/settings/proxies", json={"raw": ""}).status_code == 400
