# zoho — Zoho Mail in your terminal

[![GitHub release](https://img.shields.io/github/v/release/robsannaa/zoho-cli)](https://github.com/robsannaa/zoho-cli/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Fast, script-friendly CLI for Zoho Mail. JSON output by default, Markdown tables with `--md`. Pipe to `jq`, use in scripts, or feed directly to AI agents.

Built in the spirit of [steipete/gog](https://github.com/steipete/gog) — a Google Workspace CLI designed to give LLMs and AI agents (like [OpenClaw](https://openclaw.ai)) direct access to your tools without any middleman. You create your own Zoho OAuth app, connect it once, and you're done. No third-party service, no subscription, no data leaving your machine. Free forever.

```bash
$ zoho mail list
[
  {
    "messageId": "1771333290108014300",
    "subject": "Q1 invoice attached",
    "from": "billing@acme.com",
    "date": "1740067200000",
    "unread": true,
    "hasAttachments": true
  }
]

$ zoho --md mail list
| ID                   | FROM            | SUBJECT              | DATE   | UNREAD |
| -------------------- | --------------- | -------------------- | ------ | ------ |
| 1771333290108014300  | billing@acme.com| Q1 invoice attached  | Feb 20 | ●      |
```

---

## Install

**Requires Python 3.11+. Works on macOS, Linux, and Windows.**

```bash
# Homebrew (macOS / Linux)
brew install robsannaa/tap/zoho-cli
# If you see "missing dependency 'idna'" (or similar), run: brew reinstall zoho-cli
# Tap maintainers: ensure the formula lists all deps (e.g. brew update-python-resources zoho-cli in the tap repo).

# uv (all platforms)
uv tool install git+https://github.com/robsannaa/zoho-cli

# pipx (all platforms)
pipx install git+https://github.com/robsannaa/zoho-cli
```

Or from source:

```bash
git clone https://github.com/robsannaa/zoho-cli
cd zoho-cli
uv tool install .
```

---

## Setup

### 1 — Create an OAuth client in Zoho

1. Go to **[api-console.zoho.com](https://api-console.zoho.com/)** (or your regional console, e.g. [api-console.zoho.eu](https://api-console.zoho.eu/)) → **Add Client** → **Mobile/Desktop Application**.

   > **Important:** You must choose **Mobile/Desktop Application**, not "Server-based Applications". Only this client type allows `localhost` redirect URIs.

2. Fill in:

   | Field | Value |
   |---|---|
   | Client Name | `zoho-cli` |
   | Homepage URL | `https://example.com` |
   | Authorized Redirect URIs | `http://localhost:51821/callback` |

   > The CLI spins up a local server on port 51821 to capture the OAuth code automatically — no copy-pasting URLs.
   >
   > For headless/CI use, also add `https://example.com/zoho/oauth/callback` and use `zoho login --no-browser`.

3. Copy the **Client ID** and **Client Secret**.

### 2 — Save credentials

```bash
zoho config init
```

Writes to the platform config dir:
- macOS: `~/Library/Application Support/zoho-cli/config.json`
- Linux: `~/.config/zoho-cli/config.json`
- Windows: `%APPDATA%\zoho-cli\config.json`

### 3 — Log in

```bash
zoho login
```

Your browser opens, you approve access, and a "You're connected" page confirms success. Tokens are stored in your OS keyring — you never log in again.

**Region is auto-detected** — the CLI probes all Zoho data centres in parallel and picks the right one for your client ID. EU, India, Australia, Japan, Canada accounts all work without any extra config.

**Headless / SSH:**

```bash
zoho login --no-browser
# prints URL → paste the redirect URL back into the terminal
```

---

## Global flags

| Flag | Env var | Description |
|---|---|---|
| `--account EMAIL` | `ZOHO_ACCOUNT` | Account to use |
| `--config PATH` | `ZOHO_CONFIG` | Config file path |
| `--md` | — | Markdown table output |
| `--debug` | — | HTTP + debug logs to stderr |

---

## Mail

### List

```bash
zoho mail list                          # Inbox, 50 messages
zoho mail list --folder Sent -n 20
zoho mail list --folder "My Project" --limit 100
```

Output fields: `messageId`, `folderId`, `subject`, `from`, `to`, `date`, `unread`, `hasAttachments`, `tags`.

### Search

```bash
zoho mail search "invoice 2025"                  # plain text → searches everywhere
zoho mail search "subject:invoice" -n 10         # subject only
zoho mail search "from:boss@example.com" -n 10   # by sender
zoho mail search "entire:oliwa" -n 20            # explicit full-text
```

Plain words are automatically searched across all fields (`entire:`). You can also use Zoho's search syntax directly: `subject:`, `from:`, `content:`, `entire:`, `has:attachment`, `newMails`.

### Get full message

```bash
zoho mail get MESSAGE_ID
zoho mail get MESSAGE_ID --folder-id FOLDER_ID   # faster, skips folder scan
zoho mail get MESSAGE_ID | jq '.textBody'
```

Output adds: `cc`, `bcc`, `textBody`, `htmlBody`.

### Send

```bash
# Plain text
zoho mail send --to alice@example.com --subject "Hello" --text "Hi there!"

# HTML + attachments + multiple recipients
zoho mail send \
  --to alice@example.com --to bob@example.com \
  --cc manager@example.com \
  --subject "Q1 Report" \
  --html-file report.html \
  --attach report.pdf --attach data.csv
```

### Attachments

```bash
zoho mail attachments MESSAGE_ID
zoho mail download-attachment MESSAGE_ID ATTACHMENT_ID --out ~/Downloads/invoice.pdf
```

### Flag / status operations

All accept one or more message IDs:

```bash
zoho mail mark-read   ID [ID …]
zoho mail mark-unread ID [ID …]
zoho mail move        ID [ID …] --to Archive
zoho mail spam        ID [ID …]
zoho mail not-spam    ID [ID …]
zoho mail archive     ID [ID …]
zoho mail unarchive   ID [ID …]
zoho mail delete      ID [ID …]            # → Trash
zoho mail delete      ID [ID …] --permanent
```

---

## Folders

```bash
zoho folders list
zoho folders create "Project X" [--parent-id ID]
zoho folders rename FOLDER_ID "New Name"
zoho folders delete FOLDER_ID
```

---

## Config

```bash
zoho config init    # interactive wizard
zoho config show    # dump JSON (secret redacted)
zoho config path    # show file path
```

---

## Output

JSON is always the default — in a terminal, in a pipe, everywhere. Use `--md` for markdown tables.

```bash
zoho mail list                      # JSON
zoho mail list | jq '.[].subject'   # pipe to jq
zoho --md mail list                 # markdown table
zoho --md folders list              # markdown table

# errors go to stderr as JSON, stdout stays clean
zoho mail list 2>/dev/null
```

`NO_COLOR=1` disables colour.

---

## Scripting

```bash
# all unread subjects
zoho mail list | jq -r '.[] | select(.unread) | .subject'

# download all attachments from a message
ATTS=$(zoho mail attachments "$MSG_ID" | jq -r '.[].attachmentId')
for id in $ATTS; do
  zoho mail download-attachment "$MSG_ID" "$id" --out "/tmp/$id"
done

# search → get body → send summary
BODY=$(zoho mail search "budget approval" -n 1 \
  | jq -r '.[0].messageId' \
  | xargs -I{} zoho mail get {} \
  | jq -r '.textBody')
zoho mail send --to cfo@example.com --subject "FWD: budget approval" --text "$BODY"
```

---

## Multiple accounts

```bash
zoho login --account work@company.com
zoho login --account personal@me.com

zoho --account work@company.com mail list
export ZOHO_ACCOUNT=work@company.com
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ZOHO_ACCOUNT` | — | Default account |
| `ZOHO_CONFIG` | platform default | Config file path |
| `ZOHO_BASE_URL` | `https://mail.zoho.com/api` | Mail API base (EU: `https://mail.zoho.eu/api`) |
| `ZOHO_ACCOUNTS_BASE_URL` | `https://accounts.zoho.com` | OAuth base (EU: `https://accounts.zoho.eu`) |
| `ZOHO_TOKEN_PASSWORD` | — | Passphrase for encrypted file token storage (CI/headless) |
| `NO_COLOR` | — | Disable colour |

**EU / India:** these are set automatically per-account during login. Override manually only if needed.

---

## CI / headless

```bash
# 1. Login locally with file-based token storage
export ZOHO_TOKEN_PASSWORD=ci-secret
export ZOHO_CONFIG=/tmp/zoho-ci/config.json
zoho login --no-browser

# 2. Copy config dir to CI secrets

# 3. In CI
export ZOHO_TOKEN_PASSWORD=ci-secret
export ZOHO_CONFIG=/secrets/zoho-ci/config.json
zoho mail list
```

---

## Config file

```json
{
  "client_id": "1000.XXXXXXXXX",
  "client_secret": "xxxxxxxxxxxxx",
  "redirect_uri": "https://example.com/zoho/oauth/callback",
  "default_account": "you@example.com",
  "accounts": {
    "you@example.com": {
      "accountId": "2560636000000008002",
      "scopes": ["ZohoMail.messages.ALL", "ZohoMail.folders.ALL", "ZohoMail.accounts.READ"],
      "accounts_server": "https://accounts.zoho.eu",
      "mail_base_url": "https://mail.zoho.eu/api"
    }
  }
}
```

---

## Troubleshooting

**`No stored token`** → run `zoho login --account you@example.com`.

**`token_refresh_failed HTTP 400`** → refresh token revoked (password change, client regenerated). Run `zoho login` again.

**`No accountId stored`** → run `zoho login` again; the CLI will re-discover it.

**"This site can't be reached" in browser** → that is expected for `https://example.com/…`. Only happens with `--no-browser`. Copy the full URL from the address bar.

**`invalid_client` on token exchange** → your account is on a different regional server. Make sure you are using the latest version; regional detection is automatic.

**keyring errors on Linux** →

```bash
sudo apt install gnome-keyring libsecret-1-0
# or use file fallback:
export ZOHO_TOKEN_PASSWORD=passphrase
```

---

## Development

```bash
uv venv && uv pip install -e ".[dev]"
source .venv/bin/activate
pytest
```

```
zoho_cli/
├── cli.py       # all Typer commands
├── api.py       # httpx client, one method per endpoint
├── auth.py      # OAuth flow, local callback server, token refresh
├── mail.py      # message formatters, folder resolution
├── folders.py   # folder formatter
├── config.py    # config load/save, env var overrides
├── storage.py   # OS keyring + encrypted file fallback
└── utils.py     # JSON/markdown output, errors, date helpers
```
