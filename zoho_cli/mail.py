"""High-level mail helpers: folder resolution, message formatting."""

import logging
from typing import Optional

from zoho_cli import utils
from zoho_cli.api import ZohoMailClient

logger = logging.getLogger(__name__)


# ── folder resolution ─────────────────────────────────────────────────────────

def resolve_folder_id(client: ZohoMailClient, account_id: str, folder_name: str) -> str:
    """Resolve a folder name or ID to its folderId string."""
    resp = client.get_folders(account_id)
    folders = resp.get("data", [])

    # Accept a numeric-looking string as a direct folderId
    if folder_name.isdigit():
        for f in folders:
            if str(f.get("folderId")) == folder_name:
                return folder_name
        return folder_name  # pass through and let the API reject it if wrong

    name_lower = folder_name.lower()
    # Exact name match
    for f in folders:
        if f.get("folderName", "").lower() == name_lower:
            return str(f["folderId"])
    # folderType match (Inbox, Sent, Drafts, Trash, Spam, …)
    for f in folders:
        if f.get("folderType", "").lower() == name_lower:
            return str(f["folderId"])

    utils.error_exit("folder_not_found", f"Folder '{folder_name}' not found")
    return ""  # unreachable


def find_folder_for_message(
    client: ZohoMailClient, account_id: str, message_id: str
) -> Optional[str]:
    """Search all folders to find which one contains the given message."""
    resp = client.get_folders(account_id)
    folders = resp.get("data", [])

    for folder in folders:
        folder_id = str(folder["folderId"])
        try:
            msgs = client.get_messages(account_id, folder_id, limit=200)
            for msg in msgs.get("data", []):
                if str(msg.get("messageId")) == message_id:
                    return folder_id
        except SystemExit:
            # skip folders that return errors (e.g. empty or access-restricted)
            continue

    return None


# ── message formatters ────────────────────────────────────────────────────────

def _to_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return val
    return [val]


def format_message_summary(msg: dict) -> dict:
    """Normalise a raw API message object into the CLI list/search schema."""
    return {
        "messageId": str(msg.get("messageId", "")),
        "folderId": str(msg.get("folderId", "")),
        "subject": msg.get("subject", ""),
        "from": msg.get("sender", msg.get("fromAddress", msg.get("from", ""))),
        "to": _to_list(msg.get("toAddress", msg.get("to", []))),
        "date": msg.get("receivedTime", msg.get("sentDateInGMT", msg.get("date", ""))),
        "unread": not bool(msg.get("isRead", False)),
        "hasAttachments": bool(msg.get("hasAttachment", False)),
        "tags": msg.get("tags", []),
    }


def format_message_content(msg: dict) -> dict:
    """Normalise a raw API content object into the CLI get schema."""
    return {
        "messageId": str(msg.get("messageId", "")),
        "folderId": str(msg.get("folderId", "")),
        "subject": msg.get("subject", ""),
        "from": msg.get("sender", msg.get("fromAddress", msg.get("from", ""))),
        "to": _to_list(msg.get("toAddress", msg.get("to", []))),
        "cc": _to_list(msg.get("ccAddress", msg.get("cc", []))),
        "bcc": _to_list(msg.get("bccAddress", msg.get("bcc", []))),
        "date": msg.get("receivedTime", msg.get("sentDateInGMT", msg.get("date", ""))),
        "unread": not bool(msg.get("isRead", False)),
        "tags": msg.get("tags", []),
        "hasAttachments": bool(msg.get("hasAttachment", False)),
        "textBody": msg.get("textBody", msg.get("content", "")),
        "htmlBody": msg.get("htmlBody", ""),
    }


def format_attachment(att: dict) -> dict:
    return {
        "attachmentId": str(att.get("attachmentId", att.get("attachId", ""))),
        "fileName": att.get("attachmentName", att.get("fileName", "")),
        "size": int(att.get("attachmentSize", att.get("size", 0))),
    }
