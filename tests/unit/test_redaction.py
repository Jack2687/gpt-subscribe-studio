"""单元测试：脱敏层（宪法第 I 条，tasks.md T008）。"""

from __future__ import annotations

from gss_core import MASK, redact, redact_mapping


def test_bearer_header_redacted() -> None:
    out = redact("Authorization: Bearer abc123def456ghi")
    assert "abc123def456ghi" not in out
    assert MASK in out


def test_access_token_value_redacted() -> None:
    out = redact('{"access_token": "super-secret-token-value"}')
    assert "super-secret-token-value" not in out


def test_session_token_redacted() -> None:
    out = redact('session_token=abcdef1234567890abcdef')
    assert "abcdef1234567890abcdef" not in out


def test_proxy_password_redacted_but_user_kept() -> None:
    out = redact("http://region-JP-sid-abc:hunter2@gateway.example:8080")
    assert "hunter2" not in out
    assert "region-JP-sid-abc" in out
    assert "gateway.example" in out


def test_cvv_and_card_number_redacted() -> None:
    out = redact("cvv=123 card_number: 4242 4242 4242 4242")  # release-check: ignore
    assert "123" not in out
    assert "4242 4242 4242 4242" not in out  # release-check: ignore
    assert out.count(MASK) >= 2


def test_jwt_redacted() -> None:
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # release-check: ignore
    out = redact(f"token={jwt}")
    assert jwt not in out


def test_redact_mapping_nested() -> None:
    payload = {
        "order": {"id": "abc", "note": "Bearer zzzzzzzzzz"},
        "cookies": ["session_token=0123456789abcdef"],
    }
    out = redact_mapping(payload)
    assert out["order"]["id"] == "abc"  # 非敏感字段保持原样
    assert "zzzzzzzzzz" not in out["order"]["note"]
    assert "0123456789abcdef" not in out["cookies"][0]


def test_non_sensitive_text_unchanged() -> None:
    text = "订单已创建，状态 created，账单国家 US"
    assert redact(text) == text
