# AGENTS.md — zoho CLI agent integration guide

This document describes how AI agents and automated systems should interact with `zoho`.

---

## Output modes

| Context | Behaviour |
|---|---|
| Terminal (TTY) | Rich tables, coloured output |
| Pipe / script | JSON to stdout automatically |
| `--json` flag | Force JSON even in a terminal |
| `--debug` flag | HTTP + internal logs to stderr only |

**Always pipe stdout for JSON:**

```bash
zoho mail list | jq '.[0].messageId'
zoho --json folders list | jq '.[].folderName'
```

Errors are always written to **stderr** as JSON when piped, so stdout stays clean:

```json
{"status": "error", "error": "not_logged_in", "details": "..."}
```

---

## Authentication for agents / CI

Set credentials in environment variables or the config file; use the OS keyring or
`ZOHO_TOKEN_PASSWORD` for file-based token storage:

```bash
export ZOHO_ACCOUNT=bot@example.com
export ZOHO_CONFIG=/secrets/zoho-config.json
export ZOHO_TOKEN_PASSWORD=my-secret-passphrase   # enables file fallback
```

Perform a one-time login interactively, then all subsequent commands refresh the
token automatically — no browser required after the initial `zoho login`.

---

## Recommended patterns

### List unread messages

```bash
zoho mail list --folder Inbox --limit 100 | jq '[.[] | select(.unread)]'
```

### Get a specific message body

```bash
zoho mail get 2560636000000100001 | jq '.textBody'
```

### Search and process

```bash
zoho mail search "invoice" | jq -r '.[] | [.messageId, .from, .subject] | @tsv'
```

### Send programmatically

```bash
zoho mail send \
  --to recipient@example.com \
  --subject "Report $(date +%F)" \
  --text "See attached." \
  --attach /tmp/report.pdf
```

### Download all attachments in a loop

```bash
zoho mail attachments "$MSG_ID" | jq -r '.[].attachmentId' | while read att_id; do
  zoho mail download-attachment "$MSG_ID" "$att_id" --out "/tmp/${att_id}.bin"
done
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (JSON error object on stderr) |

---

## Environment variables

| Variable | Purpose |
|---|---|
| `ZOHO_ACCOUNT` | Default account e-mail |
| `ZOHO_CONFIG` | Config file path override |
| `ZOHO_BASE_URL` | Mail API base URL (e.g. EU region) |
| `ZOHO_ACCOUNTS_BASE_URL` | Accounts domain override |
| `ZOHO_TOKEN_PASSWORD` | Password for file-based token storage |
| `NO_COLOR` | Disable colour output |
