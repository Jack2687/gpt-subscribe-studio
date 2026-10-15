from __future__ import annotations

import pytest

from gss_core.proxies import describe_gateway, gateway_from_input, parse_proxy_input, rewrite_proxy_exit


def test_parse_url_with_region_and_sid() -> None:
    gw = gateway_from_input("http://acct-region-US-sid-AbC123:p%40ss@gw.example.com:3010")
    assert (gw.scheme, gw.host, gw.port, gw.password) == ("http", "gw.example.com", 3010, "p@ss")
    assert (gw.region, gw.sid) == ("US", "AbC123")
    info = describe_gateway(gw)
    assert info["has_region_param"] and info["has_sid_param"]
    assert "password" not in info and "username" not in info


@pytest.mark.parametrize(
    "raw",
    [
        "acct-region-JP-sid-x1:secret@gw.example.com:3010",
        "gw.example.com:3010:acct-region-JP-sid-x1:secret",
        "socks5://acct-region-JP-sid-x1:secret@gw.example.com:3010",
    ],
)
def test_parse_accepts_common_formats(raw: str) -> None:
    gw = gateway_from_input(raw)
    assert gw.host == "gw.example.com" and gw.port == 3010
    assert gw.region == "JP" and gw.sid == "x1"
    assert gw.password == "secret"


def test_parse_keeps_provider_key_names_and_case() -> None:
    raw = "http://u_country_us_session_abc123:pw@gw.example.com:8000"
    gw = gateway_from_input(raw)
    assert (gw.region, gw.sid) == ("US", "abc123")
    out = rewrite_proxy_exit(gw.proxy_url(), region="JP", sid="NEW999")
    assert "u_country_jp_session_NEW999" in out  # 键名和小写风格沿用供应商写法


def test_parse_without_tokens_is_flagged() -> None:
    info = describe_gateway(gateway_from_input("gw.example.com:3010"))
    assert not info["has_region_param"] and not info["has_sid_param"]


@pytest.mark.parametrize("raw", ["", "not a proxy", "gw.example.com", "http://gw.example.com", "a b:1"])
def test_parse_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_proxy_input(raw)
