"""Tests for zoho_cli.auth — OAuth URL builders, redirect parsing, region detection."""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from zoho_cli import auth, config as cfg_mod


# ---------------------------------------------------------------------------
# parse_redirect
# ---------------------------------------------------------------------------


def test_parse_redirect_extracts_code() -> None:
    """parse_redirect returns the code and None when no accounts-server is present."""
    code, server = auth.parse_redirect("https://example.com/callback?code=abc123")
    assert code == "abc123"
    assert server is None


def test_parse_redirect_extracts_accounts_server() -> None:
    """parse_redirect returns both code and accounts-server query params."""
    url = "https://example.com/callback?code=xyz&accounts-server=https%3A%2F%2Faccounts.zoho.eu"
    code, server = auth.parse_redirect(url)
    assert code == "xyz"
    assert server == "https://accounts.zoho.eu"


def test_parse_redirect_missing_code() -> None:
    """parse_redirect calls sys.exit (via error_exit) when no code param is present."""
    with pytest.raises(SystemExit):
        auth.parse_redirect("https://example.com/callback?error=access_denied")


def test_parse_redirect_strips_whitespace() -> None:
    """Surrounding whitespace in the URL is tolerated."""
    code, _ = auth.parse_redirect("  https://example.com?code=trimmed  ")
    assert code == "trimmed"


# ---------------------------------------------------------------------------
# build_auth_url
# ---------------------------------------------------------------------------


def test_build_auth_url_contains_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_auth_url embeds the client_id in the returned URL."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    url = auth.build_auth_url(
        client_id="my_client_id",
        redirect_uri="https://example.com/cb",
        scopes=["ZohoMail.messages.ALL"],
    )
    params = parse_qs(urlparse(url).query)
    assert params["client_id"] == ["my_client_id"]


def test_build_auth_url_contains_redirect_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_auth_url embeds the redirect_uri in the returned URL."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    redirect = "https://example.com/oauth/callback"
    url = auth.build_auth_url(
        client_id="cid",
        redirect_uri=redirect,
        scopes=["ZohoMail.messages.ALL"],
    )
    params = parse_qs(urlparse(url).query)
    assert params["redirect_uri"] == [redirect]


def test_build_auth_url_contains_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scopes are joined with commas and placed in the scope parameter."""
    monkeypatch.delenv("ZOHO_ACCOUNTS_BASE_URL", raising=False)
    scopes = ["ZohoMail.messages.ALL", "ZohoMail.folders.ALL"]
    url = auth.build_auth_url("cid", "https://example.com/cb", scopes)
    params = parse_qs(urlparse(url).query)
    assert params["scope"] == [",".join(scopes)]


def test_build_auth_url_uses_env_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZOHO_ACCOUNTS_BASE_URL env var changes the base URL used."""
    monkeypatch.setenv("ZOHO_ACCOUNTS_BASE_URL", "https://accounts.zoho.eu")
    url = auth.build_auth_url("cid", "https://example.com/cb", ["scope1"])
    assert url.startswith("https://accounts.zoho.eu/")


# ---------------------------------------------------------------------------
# discover_accounts_server
# ---------------------------------------------------------------------------


def _all_servers() -> list[str]:
    """Return the token endpoint for every region."""
    return [f"{v[0]}/oauth/v2/token" for v in cfg_mod.REGIONS.values()]


@respx.mock
def test_discover_accounts_server_finds_eu() -> None:
    """EU server returning a non-invalid_client error signals it recognised the client_id."""
    eu_url = "https://accounts.zoho.eu/oauth/v2/token"
    for url in _all_servers():
        error = "invalid_code" if url == eu_url else "invalid_client"
        respx.post(url).mock(return_value=httpx.Response(200, json={"error": error}))

    result = auth.discover_accounts_server("my_client_id")
    assert result == "https://accounts.zoho.eu"


@respx.mock
def test_discover_accounts_server_fallback() -> None:
    """Falls back to accounts.zoho.com when all servers return invalid_client."""
    for url in _all_servers():
        respx.post(url).mock(
            return_value=httpx.Response(200, json={"error": "invalid_client"})
        )

    result = auth.discover_accounts_server("unknown_client")
    assert result == "https://accounts.zoho.com"


@respx.mock
def test_discover_accounts_server_finds_com() -> None:
    """COM server returning invalid_code is identified correctly."""
    com_url = "https://accounts.zoho.com/oauth/v2/token"
    for url in _all_servers():
        error = "invalid_code" if url == com_url else "invalid_client"
        respx.post(url).mock(return_value=httpx.Response(200, json={"error": error}))

    result = auth.discover_accounts_server("com_client")
    assert result == "https://accounts.zoho.com"


@respx.mock
def test_discover_accounts_server_ignores_network_errors() -> None:
    """A server that raises a network exception is skipped; others are still tried."""
    com_url = "https://accounts.zoho.com/oauth/v2/token"
    for url in _all_servers():
        if url == com_url:
            respx.post(url).mock(return_value=httpx.Response(200, json={"error": "invalid_code"}))
        else:
            respx.post(url).mock(side_effect=httpx.ConnectError("unreachable"))

    result = auth.discover_accounts_server("client_id")
    assert result == "https://accounts.zoho.com"
