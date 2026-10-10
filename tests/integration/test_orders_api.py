"""独立开通闭环：Fake adapter 下 session + 卡标识 → delivered。"""

from __future__ import annotations

import os

os.environ["DCP_USE_FAKE"] = "1"

from fastapi.testclient import TestClient

from dcp_api.main import create_app
from dcp_api.store import store
from dcp_core.vault import vault


def test_session_and_card_token_deliver() -> None:
    store.clear()
    vault.drop("unused")
    client = TestClient(create_app())

    created = client.post(
        "/api/orders",
        json={
            "plan": "plus",
            "billing_country": "US",
            "session": '{"accessToken":"fake-session"}',
            "mode": {
                "account_source": "customer_session",
                "card_source": "customer",
                "billing_mode": "standard",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "awaiting_payment"
    assert body["billing"]["country"] == "US"
    assert body["billing"]["line1"]
    assert body["currency"] == "USD"
    assert body["amount"] == "20.00"
    order_id = body["id"]

    paid = client.post(f"/api/orders/{order_id}/pay", json={"payment_method_token": "pm_fake"})
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "delivered"
    assert paid.json()["subscription"]["active"] is True


def test_team_hosted_checkout_requires_seats_and_returns_link() -> None:
    store.clear()
    client = TestClient(create_app())
    missing = client.post(
        "/api/orders",
        json={
            "plan": "team",
            "billing_country": "JP",
            "session": '{"accessToken":"fake-session"}',
            "mode": {"account_source": "customer_session", "card_source": "customer"},
        },
    )
    assert missing.status_code == 400
    assert "席位" in missing.text

    created = client.post(
        "/api/orders",
        json={
            "plan": "team",
            "billing_country": "JP",
            "session": '{"accessToken":"fake-session"}',
            "seat_quantity": 8,
            "promo_code": "TEAM50",
            "workspace_name": "Desk",
            "mode": {"account_source": "customer_session", "card_source": "customer"},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "awaiting_payment"
    assert body["checkout_kind"] == "hosted"
    assert body["seat_quantity"] == 8
    assert body["currency"] == "JPY"
    assert body["amount"] == "200"
    assert "pay.openai.com/c/pay/" in body["checkout_url"]

    verified = client.post(f"/api/orders/{body['id']}/verify")
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "delivered"


def test_unknown_region_is_400() -> None:
    store.clear()
    client = TestClient(create_app())
    res = client.post(
        "/api/orders",
        json={
            "plan": "plus",
            "billing_country": "XX",
            "session": '{"accessToken":"fake-session"}',
            "mode": {"account_source": "customer_session", "card_source": "customer"},
        },
    )
    assert res.status_code == 400
    assert "不支持的地区" in res.text


def test_missing_session_is_401() -> None:
    store.clear()
    client = TestClient(create_app())
    res = client.post(
        "/api/orders",
        json={"plan": "plus", "billing_country": "US", "mode": {"account_source": "customer_session"}},
    )
    assert res.status_code == 401
