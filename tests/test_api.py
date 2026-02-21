"""Tests for zoho_cli.api.ZohoMailClient — HTTP interactions mocked with respx."""

from __future__ import annotations

import pytest
import httpx
import respx

from zoho_cli.api import ZohoMailClient

# Base URL used by the client when no override is given (matches config default).
BASE = "https://mail.zoho.com/api"
ACCOUNT_ID = "ACC123"


@pytest.fixture
def client() -> ZohoMailClient:
    """A ZohoMailClient wired to the default mail base URL with a fake token."""
    return ZohoMailClient(access_token="fake-token", mail_base_url=BASE)


# ---------------------------------------------------------------------------
# GET /accounts/{id}/folders
# ---------------------------------------------------------------------------


@respx.mock
def test_get_folders(client: ZohoMailClient) -> None:
    """get_folders returns the full parsed response dict from the API."""
    payload = {
        "data": [
            {"folderId": "1", "folderName": "Inbox", "folderType": "Inbox", "unreadCount": 3},
            {"folderId": "2", "folderName": "Sent", "folderType": "Sent", "unreadCount": 0},
        ]
    }
    respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = client.get_folders(ACCOUNT_ID)
    assert result == payload
    assert len(result["data"]) == 2
    assert result["data"][0]["folderName"] == "Inbox"


# ---------------------------------------------------------------------------
# GET /accounts/{id}/messages/search
# ---------------------------------------------------------------------------


@respx.mock
def test_search_messages(client: ZohoMailClient) -> None:
    """search_messages passes searchKey / limit and returns the response dict."""
    payload = {"data": [{"messageId": "101", "subject": "Invoice #42"}]}
    route = respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/messages/search").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = client.search_messages(ACCOUNT_ID, query="invoice", limit=10)
    assert result == payload
    # Verify query params were forwarded
    called_params = dict(route.calls.last.request.url.params)
    assert called_params["searchKey"] == "invoice"
    assert called_params["limit"] == "10"


# ---------------------------------------------------------------------------
# GET /accounts/{id}/messages/view
# ---------------------------------------------------------------------------


@respx.mock
def test_get_messages(client: ZohoMailClient) -> None:
    """get_messages forwards folderId / limit and returns the response dict."""
    payload = {"data": [{"messageId": "55", "subject": "Hello"}]}
    route = respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/messages/view").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = client.get_messages(ACCOUNT_ID, folder_id="FOLD1", limit=25)
    assert result == payload
    called_params = dict(route.calls.last.request.url.params)
    assert called_params["folderId"] == "FOLD1"
    assert called_params["limit"] == "25"


# ---------------------------------------------------------------------------
# POST /accounts/{id}/messages
# ---------------------------------------------------------------------------


@respx.mock
def test_send_message_json(client: ZohoMailClient) -> None:
    """send_message (no attachments) POSTs JSON and returns the response dict."""
    response_payload = {"data": {"messageId": "123", "status": "sent"}}
    respx.post(f"{BASE}/accounts/{ACCOUNT_ID}/messages").mock(
        return_value=httpx.Response(200, json=response_payload)
    )
    result = client.send_message(
        ACCOUNT_ID,
        payload={
            "fromAddress": "me@example.com",
            "toAddress": "you@example.com",
            "subject": "Hi",
            "content": "Hello",
            "mailFormat": "plaintext",
        },
    )
    assert result == response_payload
    assert result["data"]["messageId"] == "123"


# ---------------------------------------------------------------------------
# Error handling — non-2xx response
# ---------------------------------------------------------------------------


@respx.mock
def test_api_error_raises_system_exit(client: ZohoMailClient) -> None:
    """A non-success HTTP response causes error_exit to be called (SystemExit raised)."""
    respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    with pytest.raises(SystemExit) as exc_info:
        client.get_folders(ACCOUNT_ID)
    assert exc_info.value.code == 1


@respx.mock
def test_api_error_503_raises_system_exit(client: ZohoMailClient) -> None:
    """A 503 Service Unavailable also causes SystemExit via error_exit."""
    respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/messages/search").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    with pytest.raises(SystemExit) as exc_info:
        client.search_messages(ACCOUNT_ID, "test")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------


@respx.mock
def test_authorization_header_sent(client: ZohoMailClient) -> None:
    """The Zoho-oauthtoken authorization header is attached to every request."""
    route = respx.get(f"{BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client.get_folders(ACCOUNT_ID)
    auth_header = route.calls.last.request.headers.get("authorization", "")
    assert auth_header == "Zoho-oauthtoken fake-token"


# ---------------------------------------------------------------------------
# POST /accounts/{id}/folders (create)
# ---------------------------------------------------------------------------


@respx.mock
def test_create_folder(client: ZohoMailClient) -> None:
    """create_folder POSTs the folderName and returns the response dict."""
    payload = {"data": {"folderId": "99", "folderName": "MyFolder"}}
    respx.post(f"{BASE}/accounts/{ACCOUNT_ID}/folders").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = client.create_folder(ACCOUNT_ID, "MyFolder")
    assert result["data"]["folderName"] == "MyFolder"


# ---------------------------------------------------------------------------
# DELETE /accounts/{id}/folders/{folder_id}
# ---------------------------------------------------------------------------


@respx.mock
def test_delete_folder(client: ZohoMailClient) -> None:
    """delete_folder issues a DELETE request and returns the response dict."""
    payload = {"data": {"status": "success"}}
    respx.delete(f"{BASE}/accounts/{ACCOUNT_ID}/folders/99").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = client.delete_folder(ACCOUNT_ID, "99")
    assert result == payload
