"""zoho CLI — all subcommands.

Output:
- Default → JSON to stdout (pipe-friendly, agent-friendly)
- --md    → Markdown tables/text
- stderr  → errors, debug, interactive prompts (never pollutes stdout)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click
import typer

from zoho_cli import auth, config as _config, folders as _folders, mail as _mail, storage, utils
from zoho_cli.api import ZohoMailClient

# ── app setup ─────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="zoho",
    no_args_is_help=True,
    add_completion=False,
    help="Zoho Mail CLI — JSON by default, Markdown with --md.",
)
mail_app    = typer.Typer(no_args_is_help=True, help="Message operations.")
folders_app = typer.Typer(no_args_is_help=True, help="Folder management.")
config_app  = typer.Typer(no_args_is_help=True, help="Configuration helpers.")

app.add_typer(mail_app,    name="mail")
app.add_typer(folders_app, name="folders")
app.add_typer(config_app,  name="config")


# ── global state ──────────────────────────────────────────────────────────────

class _State:
    account:     Optional[str] = None
    config_path: Optional[str] = None
    debug: bool  = False
    md:   bool   = False


_S = _State()


@app.callback()
def _global(
    account: Optional[str] = typer.Option(
        None, "--account", "-a", envvar="ZOHO_ACCOUNT", help="Account e-mail to use.",
    ),
    config_path: Optional[str] = typer.Option(
        None, "--config", envvar="ZOHO_CONFIG", help="Path to config.json.",
    ),
    debug: bool = typer.Option(False, "--debug", is_flag=True, help="Log HTTP/debug to stderr."),
    md: bool    = typer.Option(False, "--md", is_flag=True, help="Markdown output instead of JSON."),
) -> None:
    _S.account     = account
    _S.config_path = config_path
    _S.debug       = debug
    _S.md          = md
    utils.configure(md=md)
    if debug:
        utils.setup_debug()


# ── shared helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return _config.load(_S.config_path)


def _require_account(cfg: dict) -> str:
    email = _S.account or _config.default_account(cfg)
    if not email:
        utils.error_exit("no_account", "No account specified. Use --account or set default_account in config.")
    return email  # type: ignore[return-value]


def _require_credentials(cfg: dict) -> tuple[str, str]:
    cid = cfg.get("client_id")
    csec = cfg.get("client_secret")
    if not cid or not csec:
        utils.error_exit("missing_credentials", "client_id and client_secret must be set. Run: zoho config init")
    return cid, csec  # type: ignore[return-value]


def _get_client(cfg: dict, email: str) -> ZohoMailClient:
    cid, csec = _require_credentials(cfg)
    account_cfg = cfg.get("accounts", {}).get(email, {})
    access_token = auth.refresh_access_token(
        email, cid, csec,
        accounts_base_url=account_cfg.get("accounts_server"),
    )
    return ZohoMailClient(access_token, mail_base_url=account_cfg.get("mail_base_url"))


def _require_account_id(cfg: dict, email: str) -> str:
    aid = cfg.get("accounts", {}).get(email, {}).get("accountId")
    if not aid:
        utils.error_exit("no_account_id", f"No accountId for {email}. Run: zoho login --account {email}")
    return str(aid)  # type: ignore[return-value]


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


# ── markdown renderers ────────────────────────────────────────────────────────

def _md_mail_list(messages: list) -> None:
    rows = [
        [
            m.get("messageId", ""),
            m.get("from", ""),
            m.get("subject", "(no subject)"),
            utils.format_date(m.get("date", "")),
            "●" if m.get("unread") else "",
        ]
        for m in messages
    ]
    print(utils.md_table(["ID", "FROM", "SUBJECT", "DATE", "UNREAD"], rows))


def _md_folders(folders: list) -> None:
    rows = [
        [
            f.get("folderName", ""),
            f.get("folderType", ""),
            str(f.get("unreadCount", 0)),
            str(f.get("messageCount", "")),
        ]
        for f in folders
    ]
    print(utils.md_table(["NAME", "TYPE", "UNREAD", "MESSAGES"], rows))


def _md_attachments(atts: list) -> None:
    rows = [
        [a.get("attachmentId", ""), a.get("fileName", ""), utils.format_size(a.get("size", 0))]
        for a in atts
    ]
    print(utils.md_table(["ID", "FILE NAME", "SIZE"], rows))


def _md_message(msg: dict) -> None:
    lines = [
        f"**Subject:** {msg.get('subject', '')}",
        f"**From:** {msg.get('from', '')}",
        f"**To:** {', '.join(msg.get('to', []))}",
    ]
    if msg.get("cc"):
        lines.append(f"**CC:** {', '.join(msg['cc'])}")
    lines += [
        f"**Date:** {utils.format_date(msg.get('date', ''))}",
        f"**Unread:** {'yes' if msg.get('unread') else 'no'}",
        "",
        "---",
        "",
        msg.get("textBody") or msg.get("htmlBody") or "_No body_",
    ]
    print("\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# zoho login
# ══════════════════════════════════════════════════════════════════════════════

@app.command("login")
def login(
    account: Optional[str] = typer.Option(
        None, "--account", "-a", envvar="ZOHO_ACCOUNT", help="Account e-mail.",
    ),
    port: int = typer.Option(
        51821, "--port", help="Local port for the OAuth callback server.",
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", is_flag=True,
        help="Print the URL instead of opening a browser (headless/remote use).",
    ),
) -> None:
    """Authenticate via Zoho OAuth 2.0."""
    cfg   = _cfg()
    email = account or _S.account or _config.default_account(cfg)
    if not email:
        email = click.prompt("Account e-mail", err=True)

    client_id     = cfg.get("client_id")
    client_secret = cfg.get("client_secret")

    if not client_id:
        client_id = click.prompt("Zoho OAuth Client ID", err=True)
        cfg["client_id"] = client_id
    if not client_secret:
        client_secret = click.prompt("Zoho OAuth Client Secret", hide_input=True, err=True)
        cfg["client_secret"] = client_secret

    # ── resolve the correct regional accounts server ───────────────────────
    # Priority: ZOHO_ACCOUNTS_BASE_URL env > cached config > auto-detect
    import os
    forced_accounts_url = _config.infer_accounts_server(cfg)
    if not forced_accounts_url:
        _stderr("Auto-detecting your Zoho region…")
        forced_accounts_url = auth.discover_accounts_server(client_id)
        _stderr(f"Detected: {forced_accounts_url}")

    os.environ["ZOHO_ACCOUNTS_BASE_URL"] = forced_accounts_url

    scopes = auth.DEFAULT_SCOPES

    if no_browser:
        # ── manual paste flow (headless / remote) ─────────────────────────
        redirect_uri = cfg.get("redirect_uri", "https://example.com/zoho/oauth/callback")
        auth_url = auth.build_auth_url(client_id, redirect_uri, scopes)
        _stderr("\n── Zoho OAuth Login (manual) ──────────────────────────────")
        _stderr("1. Open this URL in your browser:\n")
        _stderr(f"   {auth_url}\n")
        _stderr("2. Approve access.")
        _stderr("3. Copy the full redirect URL and paste it below.")
        _stderr("────────────────────────────────────────────────────────────\n")
        raw_url = click.prompt("Paste the full redirect URL here", err=True)
        code, accounts_server = auth.parse_redirect(raw_url)
    else:
        # ── browser flow with local callback server ────────────────────────
        redirect_uri, code, accounts_server = auth.browser_login_flow(
            client_id, scopes, preferred_port=port,
        )

    token_resp = auth.exchange_code(
        code, client_id, client_secret, redirect_uri,
        accounts_base_url=accounts_server,
    )
    refresh_token = token_resp["refresh_token"]
    access_token  = token_resp["access_token"]

    storage.store_token(email, refresh_token, scopes, accounts_server=accounts_server)

    # Derive regional Mail API URL from the accounts server
    mail_base: Optional[str] = None
    if accounts_server:
        mail_base = accounts_server.replace("accounts.", "mail.").rstrip("/") + "/api"

    account_id = auth.discover_account_id(access_token, mail_base_url=mail_base)

    cfg.setdefault("accounts", {})[email] = {
        "accountId": account_id,
        "scopes": scopes,
        **({"accounts_server": accounts_server} if accounts_server else {}),
        **({"mail_base_url": mail_base} if mail_base else {}),
    }
    if not cfg.get("default_account"):
        cfg["default_account"] = email
    # Cache the regional server at the top level so future `zoho login` calls
    # auto-detect the right server without needing --region
    if accounts_server and not cfg.get("accounts_server"):
        cfg["accounts_server"] = accounts_server
    _config.save(cfg, _S.config_path)

    if utils.is_md_mode():
        _stderr(f"\n✓  Connected as {email}  (accountId: {account_id})\n")
        _stderr("Next steps:\n")
        _stderr("  zoho folders list")
        _stderr("  zoho mail list")
        _stderr('  zoho mail search "invoice"')
        _stderr("  zoho mail list | jq '.[].subject'")
    else:
        utils.output_status(
            f"Logged in as {email}",
            extra={"account": email, "scopes": scopes, "accountId": account_id},
        )


# ══════════════════════════════════════════════════════════════════════════════
# zoho mail …
# ══════════════════════════════════════════════════════════════════════════════

@mail_app.command("list")
def mail_list(
    folder: str = typer.Option("Inbox", "--folder", "-f", help="Folder name or ID."),
    limit:  int  = typer.Option(50,      "--limit",  "-n", help="Max messages."),
) -> None:
    """List messages in a folder."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    folder_id = _mail.resolve_folder_id(client, account_id, folder)
    resp      = client.get_messages(account_id, folder_id, limit=limit)
    messages  = [_mail.format_message_summary(m) for m in resp.get("data", [])]
    utils.output(messages, md_render=_md_mail_list)


@mail_app.command("search")
def mail_search(
    query: str = typer.Argument(..., help="Search query."),
    limit: int  = typer.Option(50, "--limit", "-n", help="Max results."),
) -> None:
    """Search messages."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    resp     = client.search_messages(account_id, query, limit=limit)
    messages = [_mail.format_message_summary(m) for m in resp.get("data", [])]
    utils.output(messages, md_render=_md_mail_list)


@mail_app.command("get")
def mail_get(
    message_id: str           = typer.Argument(..., help="Message ID."),
    folder_id:  Optional[str] = typer.Option(None, "--folder-id", help="Folder ID (skips auto-scan)."),
) -> None:
    """Get full message content."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    fid = folder_id or _mail.find_folder_for_message(client, account_id, message_id)
    if not fid:
        utils.error_exit("message_not_found", f"Message {message_id} not found in any folder.")

    resp = client.get_message_content(account_id, fid, message_id)
    msg  = resp.get("data", resp)
    utils.output(_mail.format_message_content(msg), md_render=_md_message)


@mail_app.command("attachments")
def mail_attachments(
    message_id: str           = typer.Argument(..., help="Message ID."),
    folder_id:  Optional[str] = typer.Option(None, "--folder-id", help="Folder ID."),
) -> None:
    """List attachments for a message."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    fid = folder_id or _mail.find_folder_for_message(client, account_id, message_id)
    if not fid:
        utils.error_exit("message_not_found", f"Message {message_id} not found in any folder.")

    resp = client.get_attachment_info(account_id, fid, message_id)
    atts = [_mail.format_attachment(a) for a in resp.get("data", [])]
    utils.output(atts, md_render=_md_attachments)


@mail_app.command("download-attachment")
def mail_download_attachment(
    message_id:    str           = typer.Argument(..., help="Message ID."),
    attachment_id: str           = typer.Argument(..., help="Attachment ID."),
    out:           str           = typer.Option(..., "--out", "-o", help="Output file path."),
    folder_id:     Optional[str] = typer.Option(None, "--folder-id", help="Folder ID."),
) -> None:
    """Download an attachment to a file."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    fid = folder_id or _mail.find_folder_for_message(client, account_id, message_id)
    if not fid:
        utils.error_exit("message_not_found", f"Message {message_id} not found in any folder.")

    data     = client.download_attachment(account_id, fid, message_id, attachment_id)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    utils.output_status(
        f"Saved {out_path.name} ({utils.format_size(len(data))})",
        extra={"path": str(out_path.resolve()), "size": len(data)},
    )


@mail_app.command("send")
def mail_send(
    to:        List[str]      = typer.Option(...,  "--to",        help="Recipient (repeatable)."),
    subject:   str            = typer.Option(...,  "--subject", "-s", help="Subject line."),
    text:      Optional[str]  = typer.Option(None, "--text",       help="Plain-text body."),
    html_file: Optional[str]  = typer.Option(None, "--html-file",  help="Path to HTML body file."),
    cc:        List[str]      = typer.Option([],   "--cc",         help="CC address (repeatable)."),
    bcc:       List[str]      = typer.Option([],   "--bcc",        help="BCC address (repeatable)."),
    attach:    List[str]      = typer.Option([],   "--attach",     help="Attachment path (repeatable)."),
    from_addr: Optional[str]  = typer.Option(None, "--from",       help="Sender address override."),
) -> None:
    """Send an email."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    html_body: Optional[str] = None
    if html_file:
        p = Path(html_file)
        if not p.exists():
            utils.error_exit("file_not_found", f"HTML file not found: {html_file}")
        html_body = p.read_text()

    if not text and not html_body:
        utils.error_exit("missing_body", "Provide --text and/or --html-file.")

    payload: dict = {
        "fromAddress": from_addr or email,
        "toAddress":   ",".join(to),
        "subject":     subject,
        "mailFormat":  "html" if html_body else "plaintext",
        "content":     html_body or text or "",
    }
    if cc:  payload["ccAddress"]  = ",".join(cc)
    if bcc: payload["bccAddress"] = ",".join(bcc)
    if text and html_body:
        payload["altText"] = text

    resp   = client.send_message(account_id, payload, attachment_paths=attach or None)
    sent   = resp.get("data", resp)
    msg_id = str(sent.get("messageId", ""))
    utils.output_status(f"Sent to {', '.join(to)}", extra={"messageId": msg_id})


# ── bulk helpers ──────────────────────────────────────────────────────────────

def _bulk(mode: str, ids: list[str], label: str, **extra) -> None:
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    resp    = client.update_message(account_id, mode, ids, **extra)
    status  = resp.get("data", {})
    updated = status.get("updatedMessages", ids)
    failed  = status.get("failedMessages", [])
    n       = len(updated)
    utils.output_status(
        f"{label}: {n} message{'s' if n != 1 else ''}",
        extra={"updated": updated, "failed": failed},
    )


@mail_app.command("mark-read")
def mail_mark_read(ids: List[str] = typer.Argument(...)) -> None:
    """Mark messages as read."""
    _bulk("markAsRead", list(ids), "Marked read")


@mail_app.command("mark-unread")
def mail_mark_unread(ids: List[str] = typer.Argument(...)) -> None:
    """Mark messages as unread."""
    _bulk("markAsUnread", list(ids), "Marked unread")


@mail_app.command("move")
def mail_move(
    ids: List[str] = typer.Argument(...),
    to:  str       = typer.Option(..., "--to", help="Destination folder name or ID."),
) -> None:
    """Move messages to a folder."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    folder_id = _mail.resolve_folder_id(client, account_id, to)
    resp   = client.update_message(account_id, "move", list(ids), folderId=folder_id)
    status = resp.get("data", {})
    utils.output_status(
        f"Moved {len(ids)} message(s) to {to}",
        extra={
            "updated": status.get("updatedMessages", list(ids)),
            "failed":  status.get("failedMessages", []),
        },
    )


@mail_app.command("spam")
def mail_spam(ids: List[str] = typer.Argument(...)) -> None:
    """Mark messages as spam."""
    _bulk("markAsSpam", list(ids), "Marked as spam")


@mail_app.command("not-spam")
def mail_not_spam(ids: List[str] = typer.Argument(...)) -> None:
    """Mark messages as not spam."""
    _bulk("markAsNotSpam", list(ids), "Marked as not spam")


@mail_app.command("archive")
def mail_archive(ids: List[str] = typer.Argument(...)) -> None:
    """Archive messages."""
    _bulk("archive", list(ids), "Archived")


@mail_app.command("unarchive")
def mail_unarchive(ids: List[str] = typer.Argument(...)) -> None:
    """Unarchive messages."""
    _bulk("unarchive", list(ids), "Unarchived")


@mail_app.command("delete")
def mail_delete(
    ids:       List[str] = typer.Argument(...),
    permanent: bool      = typer.Option(False, "--permanent", is_flag=True, help="Hard delete."),
) -> None:
    """Delete messages (Trash by default; --permanent for hard delete)."""
    mode  = "hardDelete" if permanent else "moveToTrash"
    label = "Permanently deleted" if permanent else "Moved to Trash"
    _bulk(mode, list(ids), label)


# ══════════════════════════════════════════════════════════════════════════════
# zoho folders …
# ══════════════════════════════════════════════════════════════════════════════

@folders_app.command("list")
def folders_list() -> None:
    """List all folders."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    resp   = client.get_folders(account_id)
    result = [_folders.format_folder(f) for f in resp.get("data", [])]
    utils.output(result, md_render=_md_folders)


@folders_app.command("create")
def folders_create(
    name:      str           = typer.Argument(..., help="New folder name."),
    parent_id: Optional[str] = typer.Option(None, "--parent-id", help="Parent folder ID."),
) -> None:
    """Create a custom folder."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    resp = client.create_folder(account_id, name, parent_id=parent_id)
    utils.output_status(f"Created folder '{name}'", extra={"folder": _folders.format_folder(resp.get("data", {}))})


@folders_app.command("rename")
def folders_rename(
    folder_id: str = typer.Argument(..., help="Folder ID."),
    name:      str = typer.Argument(..., help="New name."),
) -> None:
    """Rename a folder."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    resp = client.update_folder(account_id, folder_id, name)
    utils.output_status(f"Renamed to '{name}'", extra={"folder": _folders.format_folder(resp.get("data", {}))})


@folders_app.command("delete")
def folders_delete(folder_id: str = typer.Argument(..., help="Folder ID.")) -> None:
    """Delete a custom folder."""
    cfg       = _cfg()
    email     = _require_account(cfg)
    client    = _get_client(cfg, email)
    account_id = _require_account_id(cfg, email)

    client.delete_folder(account_id, folder_id)
    utils.output_status(f"Deleted folder {folder_id}", extra={"folderId": folder_id})


# ══════════════════════════════════════════════════════════════════════════════
# zoho config …
# ══════════════════════════════════════════════════════════════════════════════

@config_app.command("show")
def config_show() -> None:
    """Dump the current config as JSON (client_secret redacted)."""
    cfg = dict(_cfg())
    if "client_secret" in cfg:
        cfg["client_secret"] = "***"
    utils.output_json(cfg)


@config_app.command("path")
def config_path_cmd() -> None:
    """Show the config file path."""
    p = _config.config_path(_S.config_path)
    utils.output_json({"config_path": str(p), "exists": p.exists()})


@config_app.command("init")
def config_init() -> None:
    """Interactively create or update configuration."""
    cfg = _cfg()
    p   = _config.config_path(_S.config_path)
    _stderr(f"Config: {p}")
    _stderr("Press Enter to keep existing values.\n")

    cfg["client_id"] = click.prompt(
        "Zoho OAuth Client ID", default=cfg.get("client_id", ""), err=True,
    )
    cfg["client_secret"] = click.prompt(
        "Zoho OAuth Client Secret",
        default=cfg.get("client_secret", ""),
        hide_input=True, confirmation_prompt=False, err=True,
    )
    cfg["redirect_uri"] = click.prompt(
        "Redirect URI (for --no-browser mode)",
        default=cfg.get("redirect_uri", "https://example.com/zoho/oauth/callback"),
        err=True,
    )
    cfg["default_account"] = click.prompt(
        "Default account e-mail", default=cfg.get("default_account", ""), err=True,
    )
    _config.save(cfg, _S.config_path)
    utils.output_status(f"Config saved", extra={"config_path": str(p)})
