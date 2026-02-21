"""Tests for zoho_cli.cli — Typer commands via CliRunner, HTTP mocked with respx."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from typer.testing import CliRunner

from zoho_cli import auth
from zoho_cli.cli import app

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

MAIL_BASE = "https://mail.zoho.com/api"
ACCOUNTS_BASE = "https://accounts.zoho.com"
ACCOUNT_EMAIL = "test@example.com"
ACCOUNT_ID = "ACC123"

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config(tmp_path: Path) -> Path:
    """Write a minimal valid config.json to tmp_path and return its path."""
    cfg = {
        "client_id": "test_id",
        "client_secret": "test_secret",
        "default_account": ACCOUNT_EMAIL,
        "accounts": {
            ACCOUNT_EMAIL: {
                "accountId": ACCOUNT_ID,
                "scopes": [
                    "ZohoMail.messages.ALL",
                    "ZohoMail.folders.ALL",
                    "ZohoMail.accounts.READ",
                ],
            }
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    return cfg_path


@pytest.fixture
def mock_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch keyring so get_password returns a valid JSON token, set_password is a no-op."""
    token_data = json.dumps(
        {
            "refresh_token": "rtoken123",
            "scopes": ["ZohoMail.messages.ALL"],
            "created_at": "2025-01-01T00:00:00+00:00",
        }
    )
    monkeypatch.setattr("keyring.get_password", lambda service, username: token_data)
    monkeypatch.setattr("keyring.set_password", lambda service, username, password: None)


@pytest.fixture
def mock_token_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch auth.refresh_access_token to return a fake access token directly."""
    monkeypatch.setattr(auth, "refresh_access_token", lambda *a, **kw: "fake-access-token")


def _cfg_env(cfg_path: Path) -> dict[str, str]:
    """Build an env dict that points the CLI at the test config file."""
    return {"ZOHO_CONFIG": str(cfg_path)}


# ---------------------------------------------------------------------------
# mail search
# ---------------------------------------------------------------------------


def test_mail_search_short_query(mock_config: Path, mock_token_refresh: Any) -> None:
    """A single-character query is rejected with exit code 1 and an invalid_query error."""
    result = runner.invoke(app, ["mail", "search", "X"], env=_cfg_env(mock_config))
    assert result.exit_code == 1
    assert "invalid_query" in result.output


@respx.mock
def test_mail_search_valid(mock_config: Path, mock_token_refresh: Any) -> None:
    """A valid search query returns exit code 0 and a JSON list of message summaries."""
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/messages/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "messageId": "1001",
                        "subject": "Invoice Q1",
                        "sender": "billing@vendor.com",
                        "receivedTime": "1700000000000",
                        "isRead": False,
                    }
                ]
            },
        )
    )
    result = runner.invoke(
        app, ["mail", "search", "invoice"], env=_cfg_env(mock_config)
    )
    assert result.exit_code == 0, result.output
    messages = json.loads(result.output)
    assert isinstance(messages, list)
    assert len(messages) == 1
    assert messages[0]["messageId"] == "1001"
    assert messages[0]["subject"] == "Invoice Q1"


@respx.mock
def test_mail_search_returns_empty_list(mock_config: Path, mock_token_refresh: Any) -> None:
    """A search that finds no messages returns an empty JSON list."""
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/messages/search").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = runner.invoke(app, ["mail", "search", "nomatches"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


# ---------------------------------------------------------------------------
# mail list
# ---------------------------------------------------------------------------


@respx.mock
def test_mail_list(mock_config: Path, mock_token_refresh: Any) -> None:
    """mail list resolves the Inbox folder and returns a JSON list of messages."""
    # mail list first resolves the folder name via get_folders, then fetches messages.
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "folderId": "FOLD1",
                        "folderName": "Inbox",
                        "folderType": "Inbox",
                        "unreadCount": 2,
                    }
                ]
            },
        )
    )
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/messages/view").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "messageId": "2001",
                        "subject": "Hello World",
                        "sender": "alice@example.com",
                        "receivedTime": "1700000000000",
                        "isRead": True,
                        "folderId": "FOLD1",
                    }
                ]
            },
        )
    )
    result = runner.invoke(app, ["mail", "list"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    messages = json.loads(result.output)
    assert isinstance(messages, list)
    assert len(messages) == 1
    assert messages[0]["messageId"] == "2001"
    assert messages[0]["subject"] == "Hello World"
    assert messages[0]["from"] == "alice@example.com"


@respx.mock
def test_mail_list_limit_option(mock_config: Path, mock_token_refresh: Any) -> None:
    """The --limit option is forwarded to the API."""
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"folderId": "F1", "folderName": "Inbox", "folderType": "Inbox"}
                ]
            },
        )
    )
    route = respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/messages/view").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = runner.invoke(
        app, ["mail", "list", "--limit", "5"], env=_cfg_env(mock_config)
    )
    assert result.exit_code == 0, result.output
    called_params = dict(route.calls.last.request.url.params)
    assert called_params["limit"] == "5"


# ---------------------------------------------------------------------------
# folders list
# ---------------------------------------------------------------------------


@respx.mock
def test_folders_list(mock_config: Path, mock_token_refresh: Any) -> None:
    """folders list returns exit code 0 and a JSON list of formatted folder objects."""
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "folderId": "F1",
                        "folderName": "Inbox",
                        "folderType": "Inbox",
                        "unreadCount": 5,
                        "messageCount": 100,
                        "isArchived": 0,
                    },
                    {
                        "folderId": "F2",
                        "folderName": "Sent",
                        "folderType": "Sent",
                        "unreadCount": 0,
                        "messageCount": 42,
                        "isArchived": 0,
                    },
                ]
            },
        )
    )
    result = runner.invoke(app, ["folders", "list"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    folders = json.loads(result.output)
    assert isinstance(folders, list)
    assert len(folders) == 2
    folder_names = {f["folderName"] for f in folders}
    assert folder_names == {"Inbox", "Sent"}
    # Verify the formatter ran (folderId stringified, counts present)
    inbox = next(f for f in folders if f["folderName"] == "Inbox")
    assert inbox["folderId"] == "F1"
    assert inbox["unreadCount"] == 5


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show(mock_config: Path) -> None:
    """config show outputs JSON with client_secret redacted as '***'."""
    result = runner.invoke(app, ["config", "show"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["client_id"] == "test_id"
    # Secret must be redacted
    assert data["client_secret"] == "***"
    assert data["default_account"] == ACCOUNT_EMAIL


def test_config_show_preserves_accounts(mock_config: Path) -> None:
    """config show preserves the accounts section in its output."""
    result = runner.invoke(app, ["config", "show"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert ACCOUNT_EMAIL in data["accounts"]
    assert data["accounts"][ACCOUNT_EMAIL]["accountId"] == ACCOUNT_ID


# ---------------------------------------------------------------------------
# config path
# ---------------------------------------------------------------------------


def test_config_path_cmd(mock_config: Path) -> None:
    """config path outputs JSON containing a config_path key."""
    result = runner.invoke(app, ["config", "path"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "config_path" in data
    assert str(mock_config) == data["config_path"]


def test_config_path_cmd_exists_flag(mock_config: Path) -> None:
    """config path reports exists: true when the config file is present."""
    result = runner.invoke(app, ["config", "path"], env=_cfg_env(mock_config))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["exists"] is True


def test_config_path_cmd_nonexistent(tmp_path: Path) -> None:
    """config path reports exists: false for a path that does not exist."""
    missing = str(tmp_path / "nonexistent.json")
    result = runner.invoke(app, ["config", "path"], env={"ZOHO_CONFIG": missing})
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["exists"] is False
    assert data["config_path"] == missing


# ---------------------------------------------------------------------------
# Error propagation — missing account_id
# ---------------------------------------------------------------------------


def test_no_account_id_exits(tmp_path: Path, mock_token_refresh: Any) -> None:
    """An account entry without accountId causes exit code 1."""
    cfg = {
        "client_id": "cid",
        "client_secret": "csec",
        "default_account": ACCOUNT_EMAIL,
        "accounts": {ACCOUNT_EMAIL: {"scopes": []}},  # no accountId
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    result = runner.invoke(app, ["folders", "list"], env=_cfg_env(cfg_path))
    assert result.exit_code == 1
    assert "no_account_id" in result.output


# ---------------------------------------------------------------------------
# Keyring-based token flow (no mock_token_refresh fixture)
# ---------------------------------------------------------------------------


@respx.mock
def test_mail_search_via_keyring(
    mock_config: Path, mock_keyring: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full flow: keyring provides refresh token → token exchange → search API."""
    # Token refresh HTTP call
    respx.post(f"{ACCOUNTS_BASE}/oauth/v2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "live-token"})
    )
    # Search API call
    respx.get(f"{MAIL_BASE}/accounts/{ACCOUNT_ID}/messages/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "messageId": "9001",
                        "subject": "Keyring test",
                        "sender": "bob@example.com",
                    }
                ]
            },
        )
    )
    result = runner.invoke(
        app, ["mail", "search", "keyring test"], env=_cfg_env(mock_config)
    )
    assert result.exit_code == 0, result.output
    messages = json.loads(result.output)
    assert messages[0]["messageId"] == "9001"
