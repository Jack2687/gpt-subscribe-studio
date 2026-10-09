"""单元测试：配置加载（tasks.md T009）。"""

from __future__ import annotations

import json
from pathlib import Path

from dcp_core.config import (
    ENV_SENTINEL_VERSION,
    ENV_STRIPE_PUBLISHABLE_KEY,
    load_settings,
    missing_upstreams,
)


def test_defaults_are_loopback_and_promo_off(tmp_path: Path) -> None:
    settings = load_settings(config_dir=tmp_path, env={})
    assert settings.bind_host == "127.0.0.1"
    assert settings.enable_promo_mode is False


def test_env_overrides_applied(tmp_path: Path) -> None:
    env = {
        "DCP_BIND_PORT": "9090",
        "DCP_ENABLE_PROMO": "true",
        "DCP_DATA_DIR": str(tmp_path / "data"),
    }
    settings = load_settings(config_dir=tmp_path, env=env)
    assert settings.bind_port == 9090
    assert settings.enable_promo_mode is True
    assert settings.db_path == tmp_path / "data" / "app.db"


def test_emergency_overrides_captured(tmp_path: Path) -> None:
    env = {
        ENV_STRIPE_PUBLISHABLE_KEY: "pk_live_xxx",
        ENV_SENTINEL_VERSION: "2026-10-01",
    }
    settings = load_settings(config_dir=tmp_path, env=env)
    assert settings.emergency_overrides[ENV_STRIPE_PUBLISHABLE_KEY] == "pk_live_xxx"
    assert settings.emergency_overrides[ENV_SENTINEL_VERSION] == "2026-10-01"


def test_shards_take_priority_over_legacy_config(tmp_path: Path) -> None:
    (tmp_path / "runtime.json").write_text(json.dumps({"from_shard": True}), encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps({"from_shard": False, "legacy": True}), encoding="utf-8"
    )
    settings = load_settings(config_dir=tmp_path, env={})
    assert settings.extra["from_shard"] is True
    assert "legacy" not in settings.extra


def test_legacy_config_used_when_no_shards(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"legacy": True}), encoding="utf-8")
    settings = load_settings(config_dir=tmp_path, env={})
    assert settings.extra["legacy"] is True


def test_upstream_paths_and_missing_report(tmp_path: Path) -> None:
    env = {"UPSTREAM_ZKKY_PATH": "/opt/zkky"}
    settings = load_settings(config_dir=tmp_path, env=env)
    assert settings.upstream_paths["UPSTREAM_ZKKY_PATH"] == "/opt/zkky"
    missing = missing_upstreams(settings)
    assert any("GPT-Register-Tool" in item for item in missing)
    assert all("zkky" not in item for item in missing)
