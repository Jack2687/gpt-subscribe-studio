import base64
import json

import pytest

from gss_core.session_token import parse_session, parse_session_bundle


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


# 运行时拼出的占位 token，仓库里不出现完整的 JWT 字面量。
_JWE_HEADER = _b64('{"alg":"dir","enc":"A256GCM"}')
_JWS_HEADER = _b64('{"alg":"RS256","typ":"JWT"}')


def test_plain_token() -> None:
    assert parse_session("  eyJabc.def.ghi  ") == "eyJabc.def.ghi"


def test_bearer_prefix() -> None:
    assert parse_session("Bearer tok_123") == "tok_123"


def test_json_access_token() -> None:
    raw = '{"accessToken":"tok_from_json","user":{"email":"a@b.c"}}'
    assert parse_session(raw) == "tok_from_json"


def test_full_session_keeps_cookie_and_device() -> None:
    raw = json.dumps(
        {
            "accessToken": "tok_from_json",
            "sessionToken": "sess_from_json",
            "sessionId": "sid-from-json",
            "cookie_header": "cf_clearance=cf-1; oai-did=did-cookie",
        }
    )
    bundle = parse_session_bundle(raw)
    assert bundle.access_token == "tok_from_json"
    assert bundle.session_token == "sess_from_json"
    assert bundle.device_id == "did-cookie"
    assert bundle.oai_session_id == "sid-from-json"
    assert bundle.cookies["cf_clearance"] == "cf-1"
    assert bundle.cookies["__Secure-next-auth.session-token"] == "sess_from_json"


def test_nested_session_object() -> None:
    raw = json.dumps({"session": {"accessToken": "nested-at", "sessionToken": "nested-st"}})
    bundle = parse_session_bundle(raw)
    assert bundle.access_token == "nested-at"
    assert bundle.session_token == "nested-st"


def test_cookie_only_paste_is_rejected() -> None:
    with pytest.raises(ValueError, match="整段 session"):
        parse_session_bundle("oai-did=did-1; __Secure-next-auth.session-token=sess-1")


def test_jwe_session_token_recognized() -> None:
    """5段 JWE（session token）应该被识别为 session_token 而非 access_token"""
    jwe_token = f"{_JWE_HEADER}..abc123.def456.ghi789"
    bundle = parse_session_bundle(jwe_token)
    assert bundle.access_token == ""
    assert bundle.session_token == jwe_token


def test_jws_access_token_recognized() -> None:
    """3段 JWS（access token）应该被识别为 access_token"""
    jws_token = f"{_JWS_HEADER}.payload.signature"
    bundle = parse_session_bundle(jws_token)
    assert bundle.access_token == jws_token
    assert bundle.session_token == ""


def test_session_token_with_prefix() -> None:
    """带前缀的 session token"""
    jwe_token = f"{_JWE_HEADER}..abc.def.ghi"
    bundle = parse_session_bundle(f"__Secure-next-auth.session-token={jwe_token}")
    assert bundle.access_token == ""
    assert bundle.session_token == jwe_token

