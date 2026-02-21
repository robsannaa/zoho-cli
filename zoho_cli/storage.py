"""Token storage backed by the OS keyring with optional file fallback."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import keyring
import keyring.errors

from zoho_cli import config as _config

SERVICE_NAME = "zoho-cli"
logger = logging.getLogger(__name__)


def store_token(
    email: str,
    refresh_token: str,
    scopes: list[str],
    accounts_server: Optional[str] = None,
) -> None:
    data = {
        "refresh_token": refresh_token,
        "scopes": scopes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if accounts_server:
        data["accounts_server"] = accounts_server
    _store_raw(email, json.dumps(data))


def load_token(email: str) -> Optional[dict]:
    raw = _load_raw(email)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Corrupted token data for %s", email)
        return None


def delete_token(email: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, email)
    except keyring.errors.PasswordDeleteError:
        pass
    # Also remove fallback file if present
    _fallback_path(email).unlink(missing_ok=True)


# ── internal helpers ──────────────────────────────────────────────────────────

def _fallback_path(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return Path(_config.config_path().parent) / f"token_{safe}.json"


def _store_raw(email: str, value: str) -> None:
    password = os.environ.get("ZOHO_TOKEN_PASSWORD")
    if password:
        _file_store(email, value, password)
        return
    try:
        keyring.set_password(SERVICE_NAME, email, value)
    except Exception as exc:
        logger.debug("keyring write failed (%s), falling back to file", exc)
        _file_store(email, value, password="")


def _load_raw(email: str) -> Optional[str]:
    password = os.environ.get("ZOHO_TOKEN_PASSWORD")
    if password:
        return _file_load(email, password)
    try:
        val = keyring.get_password(SERVICE_NAME, email)
        if val is not None:
            return val
    except Exception as exc:
        logger.debug("keyring read failed (%s), trying file fallback", exc)
    return _file_load(email, password="")


def _file_store(email: str, value: str, password: str) -> None:
    path = _fallback_path(email)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Simple XOR obfuscation when a password is provided (not crypto-grade)
    if password:
        import base64
        key = (password * (len(value) // len(password) + 1))[: len(value)]
        obfuscated = bytes(a ^ b for a, b in zip(value.encode(), key.encode()))
        path.write_bytes(base64.b64encode(obfuscated))
    else:
        path.write_text(value)
    path.chmod(0o600)


def _file_load(email: str, password: str) -> Optional[str]:
    path = _fallback_path(email)
    if not path.exists():
        return None
    if password:
        import base64
        raw = base64.b64decode(path.read_bytes())
        key = (password * (len(raw) // len(password) + 1))[: len(raw)]
        return bytes(a ^ b for a, b in zip(raw, key.encode())).decode()
    return path.read_text()
