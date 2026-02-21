"""Tests for zoho_cli.config — path helpers, load/save, and server inference."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from zoho_cli import config as cfg_mod


# ---------------------------------------------------------------------------
# config_path
# ---------------------------------------------------------------------------


def test_config_path_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """config_path() without arguments returns a Path object."""
    # Clear any env override so we get the platformdirs default path.
    monkeypatch.delenv("ZOHO_CONFIG", raising=False)
    result = cfg_mod.config_path()
    assert isinstance(result, Path)


def test_config_path_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ZOHO_CONFIG env var is honoured by config_path()."""
    override = str(tmp_path / "env_config.json")
    monkeypatch.setenv("ZOHO_CONFIG", override)
    assert cfg_mod.config_path() == Path(override)


def test_config_path_explicit_override(tmp_path: Path) -> None:
    """An explicit override argument takes the highest priority."""
    override = str(tmp_path / "explicit.json")
    assert cfg_mod.config_path(override) == Path(override)


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def test_config_load_missing(tmp_path: Path) -> None:
    """load() returns an empty dict when the config file does not exist."""
    missing = str(tmp_path / "does_not_exist.json")
    result = cfg_mod.load(missing)
    assert result == {}


def test_config_load_existing(tmp_path: Path) -> None:
    """load() parses JSON from an existing config file."""
    cfg_file = tmp_path / "config.json"
    data = {"client_id": "abc", "client_secret": "xyz"}
    cfg_file.write_text(json.dumps(data))
    result = cfg_mod.load(str(cfg_file))
    assert result == data


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------


def test_config_save_and_load(tmp_path: Path) -> None:
    """save() writes JSON that load() can read back identically."""
    cfg_file = str(tmp_path / "config.json")
    original = {
        "client_id": "cid",
        "client_secret": "csec",
        "default_account": "user@example.com",
        "accounts": {
            "user@example.com": {
                "accountId": "ACC999",
                "scopes": ["ZohoMail.messages.ALL"],
            }
        },
    }
    cfg_mod.save(original, cfg_file)
    loaded = cfg_mod.load(cfg_file)
    assert loaded == original


def test_config_save_creates_parent_dirs(tmp_path: Path) -> None:
    """save() creates intermediate directories if they do not exist."""
    deep_path = str(tmp_path / "a" / "b" / "c" / "config.json")
    cfg_mod.save({"key": "val"}, deep_path)
    assert Path(deep_path).exists()
    assert json.loads(Path(deep_path).read_text()) == {"key": "val"}


# ---------------------------------------------------------------------------
# default_account
# ---------------------------------------------------------------------------


def test_default_account_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZOHO_ACCOUNT env var overrides the config's default_account."""
    monkeypatch.setenv("ZOHO_ACCOUNT", "env@example.com")
    result = cfg_mod.default_account({"default_account": "cfg@example.com"})
    assert result == "env@example.com"


def test_default_account_from_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    """cfg['default_account'] is used when ZOHO_ACCOUNT is absent."""
    monkeypatch.delenv("ZOHO_ACCOUNT", raising=False)
    result = cfg_mod.default_account({"default_account": "cfg@example.com"})
    assert result == "cfg@example.com"


def test_default_account_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """None is returned when neither env var nor config key are set."""
    monkeypatch.delenv("ZOHO_ACCOUNT", raising=False)
    result = cfg_mod.default_account({})
    assert result is None


# ---------------------------------------------------------------------------
# infer_accounts_server
# ---------------------------------------------------------------------------


def test_infer_accounts_server_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZOHO_ACCOUNTS_BASE_URL env var is returned first."""
    monkeypatch.setenv("ZOHO_ACCOUNTS_BASE_URL", "https://accounts.zoho.eu")
    result = cfg_mod.infer_accounts_server({})
    assert result == "https://accounts.zoho.eu"


def test_infer_accounts_server_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Top-level accounts_server key in cfg is returned when env var is absent."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    cfg = {"accounts_server": "https://accounts.zoho.in"}
    result = cfg_mod.infer_accounts_server(cfg)
    assert result == "https://accounts.zoho.in"


def test_infer_accounts_server_per_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-account accounts_server value is found when no top-level key exists."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    cfg = {
        "accounts": {
            "user@example.com": {
                "accountId": "ACC1",
                "accounts_server": "https://accounts.zoho.jp",
            }
        }
    }
    result = cfg_mod.infer_accounts_server(cfg)
    assert result == "https://accounts.zoho.jp"


def test_infer_accounts_server_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """None is returned when no server hint is found anywhere."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    result = cfg_mod.infer_accounts_server({"accounts": {"a@b.com": {"accountId": "1"}}})
    assert result is None
