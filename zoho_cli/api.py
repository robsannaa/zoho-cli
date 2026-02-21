"""Low-level Zoho Mail HTTP client.

Each method maps closely to one Zoho Mail REST endpoint.
All errors call utils.error_exit() so callers never need to check status codes.
"""

import logging
import mimetypes
from pathlib import Path
from typing import Any, Optional

import httpx

from zoho_cli import config as _config
from zoho_cli import utils

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


class ZohoMailClient:
    def __init__(self, access_token: str, mail_base_url: Optional[str] = None) -> None:
        self.access_token = access_token
        self.base_url = (mail_base_url or _config.mail_base_url()).rstrip("/")
        self._headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}

    # ── internal request helpers ──────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("GET %s params=%s", url, params)
        resp = httpx.get(url, headers=self._headers, params=params or {}, timeout=_TIMEOUT)
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} GET {path}: {resp.text}")
        return resp.json()

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("POST %s", url)
        resp = httpx.post(url, headers=self._headers, json=payload, timeout=_TIMEOUT)
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} POST {path}: {resp.text}")
        return resp.json()

    def _post_multipart(self, path: str, data: dict, files: list[tuple]) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("POST (multipart) %s", url)
        resp = httpx.post(
            url,
            headers=self._headers,
            data=data,
            files=files,
            timeout=httpx.Timeout(120.0),  # longer for uploads
        )
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} POST {path}: {resp.text}")
        return resp.json()

    def _put(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("PUT %s", url)
        resp = httpx.put(url, headers=self._headers, json=payload, timeout=_TIMEOUT)
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} PUT {path}: {resp.text}")
        return resp.json()

    def _delete(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        logger.debug("DELETE %s", url)
        resp = httpx.delete(url, headers=self._headers, timeout=_TIMEOUT)
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} DELETE {path}: {resp.text}")
        return resp.json()

    def _get_bytes(self, path: str) -> bytes:
        url = f"{self.base_url}{path}"
        logger.debug("GET (binary) %s", url)
        resp = httpx.get(url, headers=self._headers, timeout=httpx.Timeout(120.0))
        logger.debug("→ %s", resp.status_code)
        if not resp.is_success:
            utils.error_exit("api_error", f"HTTP {resp.status_code} GET {path}: {resp.text}")
        return resp.content

    # ── account ───────────────────────────────────────────────────────────────

    def get_accounts(self) -> dict:
        return self._get("/accounts")

    # ── folders ───────────────────────────────────────────────────────────────

    def get_folders(self, account_id: str) -> dict:
        return self._get(f"/accounts/{account_id}/folders")

    def create_folder(self, account_id: str, folder_name: str, parent_id: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"folderName": folder_name}
        if parent_id:
            payload["parentId"] = parent_id
        return self._post_json(f"/accounts/{account_id}/folders", payload)

    def update_folder(self, account_id: str, folder_id: str, folder_name: str) -> dict:
        return self._put(f"/accounts/{account_id}/folders/{folder_id}", {"folderName": folder_name})

    def delete_folder(self, account_id: str, folder_id: str) -> dict:
        return self._delete(f"/accounts/{account_id}/folders/{folder_id}")

    def folder_operation(self, account_id: str, folder_id: str, mode: str, **extra) -> dict:
        """Generic folder mode operation (emptyFolder, markAsRead, move, etc.)."""
        payload: dict[str, Any] = {"mode": mode}
        payload.update(extra)
        return self._put(f"/accounts/{account_id}/folders/{folder_id}", payload)

    # ── labels ────────────────────────────────────────────────────────────────

    def get_labels(self, account_id: str) -> dict:
        return self._get(f"/accounts/{account_id}/labels")

    def create_label(self, account_id: str, name: str, color: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"labelName": name}
        if color:
            payload["color"] = color
        return self._post_json(f"/accounts/{account_id}/labels", payload)

    def delete_label(self, account_id: str, label_id: str) -> dict:
        return self._delete(f"/accounts/{account_id}/labels/{label_id}")

    # ── messages ──────────────────────────────────────────────────────────────

    def get_messages(
        self,
        account_id: str,
        folder_id: str,
        limit: int = 50,
        start: int = 0,
    ) -> dict:
        params: dict[str, Any] = {"folderId": folder_id, "limit": limit}
        if start:
            params["start"] = start
        return self._get(f"/accounts/{account_id}/messages/view", params)

    def search_messages(self, account_id: str, query: str, limit: int = 50) -> dict:
        return self._get(
            f"/accounts/{account_id}/messages/search",
            {"searchKey": query, "limit": limit},
        )

    def get_message_content(
        self, account_id: str, folder_id: str, message_id: str
    ) -> dict:
        return self._get(
            f"/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/content"
        )

    def update_message(self, account_id: str, mode: str, message_ids: list[str], **extra) -> dict:
        payload: dict[str, Any] = {"mode": mode, "messageId": message_ids}
        payload.update(extra)
        return self._put(f"/accounts/{account_id}/updatemessage", payload)

    # ── attachments ───────────────────────────────────────────────────────────

    def get_attachment_info(
        self, account_id: str, folder_id: str, message_id: str
    ) -> dict:
        return self._get(
            f"/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/attachmentinfo"
        )

    def download_attachment(
        self,
        account_id: str,
        folder_id: str,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        return self._get_bytes(
            f"/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/attachments/{attachment_id}"
        )

    # ── send ──────────────────────────────────────────────────────────────────

    def send_message(
        self,
        account_id: str,
        payload: dict,
        attachment_paths: Optional[list[str]] = None,
    ) -> dict:
        if not attachment_paths:
            return self._post_json(f"/accounts/{account_id}/messages", payload)

        # Build multipart request when attachments are present
        data = {k: v for k, v in payload.items() if isinstance(v, str)}
        # lists need to be serialised as repeated keys; httpx handles list values
        for k, v in payload.items():
            if isinstance(v, list):
                data[k] = v  # type: ignore[assignment]

        files: list[tuple] = []
        handles = []
        try:
            for fpath in attachment_paths:
                p = Path(fpath)
                if not p.exists():
                    utils.error_exit("file_not_found", f"Attachment not found: {fpath}")
                mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                fh = open(p, "rb")
                handles.append(fh)
                files.append(("attachment", (p.name, fh, mime)))
            return self._post_multipart(f"/accounts/{account_id}/messages", data, files)
        finally:
            for fh in handles:
                fh.close()
