"""Tests for zoho_cli.storage fallback-path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from zoho_cli import storage


@pytest.fixture(autouse=True)
def _reset_storage_config() -> None:
    storage.configure(config_path=None)
    yield
    storage.configure(config_path=None)


def test_fallback_path_uses_env_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no override is configured, path follows ZOHO_CONFIG location."""
    cfg_path = tmp_path / "env" / "config.json"
    monkeypatch.setenv("ZOHO_CONFIG", str(cfg_path))

    path = storage._fallback_path("user@example.com")

    assert path.parent == cfg_path.parent


def test_fallback_path_uses_override_over_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Runtime override takes precedence over ZOHO_CONFIG for fallback token files."""
    env_cfg_path = tmp_path / "env" / "config.json"
    override_cfg_path = tmp_path / "override" / "config.json"
    monkeypatch.setenv("ZOHO_CONFIG", str(env_cfg_path))
    storage.configure(config_path=str(override_cfg_path))

    path = storage._fallback_path("user@example.com")

    assert path.parent == override_cfg_path.parent
