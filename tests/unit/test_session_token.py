import json

import pytest

from dcp_core.session_token import parse_session, parse_session_bundle


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
