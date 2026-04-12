"""OAuth 2.0 helpers: login flow, token exchange, token refresh."""

import html
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import httpx

from zoho_cli import config as _config
from zoho_cli import storage, utils

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = [
    "ZohoMail.messages.ALL",
    "ZohoMail.folders.ALL",
    "ZohoMail.accounts.READ",
    "ZohoMail.tags.ALL",
]

# ── success page served to the browser after OAuth ───────────────────────────

_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connected — zoho</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(145deg,#0f1117 0%,#151c2c 100%);
  color:#e2e8f0;min-height:100vh;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:2rem;gap:1.25rem;
}
.icon-wrap{position:relative;display:inline-flex;margin-bottom:.25rem}
.icon{font-size:3.5rem;line-height:1}
.badge{
  position:absolute;bottom:-2px;right:-2px;
  background:#22c55e;border-radius:50%;width:1.5rem;height:1.5rem;
  display:flex;align-items:center;justify-content:center;
  font-size:.9rem;color:#fff;font-weight:700;
}
h1{font-size:2rem;font-weight:700;letter-spacing:-.025em}
.sub{color:#64748b;font-size:.95rem}
.card{
  background:#161b27;border:1px solid #1e293b;border-radius:14px;
  padding:1.25rem 1.5rem;width:100%;max-width:500px;
}
.mono{font-family:'SF Mono','Fira Code','Cascadia Code',monospace;font-size:.8rem;line-height:2}
.p{color:#334155;user-select:none}.cmd{color:#7dd3fc}.str{color:#86efac}.dim{color:#475569}
.cursor{
  display:inline-block;width:.45rem;height:.9em;background:#475569;
  vertical-align:text-bottom;animation:blink 1.1s step-end infinite;
}
@keyframes blink{50%{opacity:0}}
.ret{display:flex;align-items:center;gap:1rem}
.ret-ico{font-size:1.5rem;flex-shrink:0}
.ret h3{font-size:.875rem;font-weight:600;margin-bottom:.25rem}
.ret p{font-size:.8rem;color:#64748b;line-height:1.5}
.ret code{color:#7dd3fc;background:#1e293b;padding:.1em .35em;border-radius:4px;font-family:monospace}
footer{color:#334155;font-size:.8rem;margin-top:.25rem}
</style>
</head>
<body>
<div class="icon-wrap"><span class="icon">✉️</span><span class="badge">✓</span></div>
<h1>You're connected</h1>
<p class="sub">zoho is now authorized to access Zoho Mail</p>

<div class="card mono">
  <div class="dim"># list your inbox</div>
  <div><span class="p">$ </span><span class="cmd">zoho mail list</span></div>
  <br>
  <div class="dim"># search messages</div>
  <div><span class="p">$ </span><span class="cmd">zoho mail search </span><span class="str">"invoice"</span></div>
  <br>
  <div class="dim"># pipe to jq</div>
  <div><span class="p">$ </span><span class="cmd">zoho mail list</span><span class="dim"> | jq '.[].subject'</span></div>
  <br>
  <div><span class="p">$ </span><span class="cursor"></span></div>
</div>

<div class="card ret">
  <span class="ret-ico">⌨️</span>
  <div>
    <h3>Return to your terminal</h3>
    <p>You can close this window. Run <code>zoho --help</code> to see all commands.</p>
  </div>
</div>

<footer>You can close this window.</footer>
</body>
</html>
"""


def _error_html(message: str) -> str:
    """HTML shown in the browser when OAuth fails (exchange or Zoho error redirect)."""
    safe = html.escape(message, quote=False)
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign-in failed — zoho</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:linear-gradient(145deg,#1a0f12 0%,#1c1518 100%);
  color:#e2e8f0;min-height:100vh;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:2rem;gap:1.25rem;
}}
.icon-wrap{{display:inline-flex;margin-bottom:.25rem}}
.icon{{font-size:3.5rem;line-height:1}}
h1{{font-size:1.75rem;font-weight:700;letter-spacing:-.025em;color:#fca5a5}}
.sub{{color:#94a3b8;font-size:.95rem;max-width:36rem;text-align:center;line-height:1.5}}
.card{{
  background:#161b27;border:1px solid #7f1d1d;border-radius:14px;
  padding:1.25rem 1.5rem;width:100%;max-width:560px;
}}
.msg{{
  font-family:'SF Mono','Fira Code','Cascadia Code',monospace;font-size:.82rem;
  color:#fecaca;line-height:1.6;white-space:pre-wrap;word-break:break-word;
}}
footer{{color:#64748b;font-size:.8rem;margin-top:.25rem;text-align:center}}
</style>
</head>
<body>
<div class="icon-wrap"><span class="icon">⚠️</span></div>
<h1>Couldn’t complete sign-in</h1>
<p class="sub">Something went wrong while connecting to Zoho. Details below — you can also check the terminal.</p>
<div class="card"><div class="msg">{safe}</div></div>
<footer>You can close this window and fix the issue, then run <code style="color:#7dd3fc">zoho login</code> again.</footer>
</body>
</html>
"""


# ── local callback server ─────────────────────────────────────────────────────

def _make_callback_handler(
    result: dict,
    client_id: str,
    client_secret: str,
    redirect_uri_holder: list,
) -> type:
    """Return a request handler that exchanges the code and serves success or error HTML.

    ``redirect_uri_holder`` is a single-element list filled with the real redirect URI
    immediately after the server binds (port may be ephemeral).
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            oauth_err = params.get("error", [None])[0]
            if oauth_err:
                desc = params.get("error_description", [oauth_err])[0] or oauth_err
                msg = unquote(desc) if desc else oauth_err
                result["oauth_error"] = msg
                body = _error_html(msg).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            code = params.get("code", [None])[0]
            accounts_server = params.get("accounts-server", [None])[0]

            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Missing code parameter.")
                return

            redirect_uri = redirect_uri_holder[0] if redirect_uri_holder else ""
            token_resp, err = try_exchange_code(
                code,
                client_id,
                client_secret,
                redirect_uri,
                accounts_base_url=accounts_server,
            )
            if err:
                result["oauth_error"] = err
                body = _error_html(err).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            result["code"] = code
            result["accounts_server"] = accounts_server
            result["token_resp"] = token_resp
            body = _SUCCESS_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass  # suppress access logs

    return _Handler


def create_callback_server(
    preferred_port: int = 51821,
    *,
    client_id: str,
    client_secret: str,
) -> tuple:
    """
    Bind the OAuth callback server immediately and return early.
    Call this BEFORE region detection so the port is held the whole time.

    Binds to 127.0.0.1 (IPv4) explicitly — on macOS, binding to "localhost"
    resolves to ::1 (IPv6) while browsers connect via 127.0.0.1 (IPv4),
    causing ERR_CONNECTION_REFUSED even though the server appears to be running.

    Returns (server, redirect_uri, result_dict).
    """
    result: dict = {}
    redirect_uri_holder: list[str] = []
    handler_cls = _make_callback_handler(result, client_id, client_secret, redirect_uri_holder)
    try:
        server = HTTPServer(("127.0.0.1", preferred_port), handler_cls)
        actual_port = preferred_port
    except OSError:
        server = HTTPServer(("127.0.0.1", 0), handler_cls)
        actual_port = server.server_address[1]
    # Keep redirect_uri as localhost (matches Zoho console registration);
    # browsers resolve localhost → 127.0.0.1 so the binding above is reached.
    redirect_uri = f"http://localhost:{actual_port}/callback"
    redirect_uri_holder.append(redirect_uri)
    return server, redirect_uri, result


def browser_login_flow(
    client_id: str,
    scopes: list[str],
    preferred_port: int = 51821,
    client_secret: str = "",
    _server=None,
    _redirect_uri: Optional[str] = None,
    _result: Optional[dict] = None,
) -> tuple[str, str, Optional[str], Optional[dict]]:
    """
    Open the browser, wait for the OAuth callback.

    Returns (redirect_uri, code, accounts_server, token_resp).
    ``token_resp`` is set when the callback handler completed the token exchange;
    otherwise ``None`` (caller should call ``exchange_code``).
    """
    import time
    import webbrowser

    if _server is not None and _redirect_uri is not None and _result is not None:
        server, redirect_uri, result = _server, _redirect_uri, _result
    else:
        if not client_secret:
            utils.error_exit(
                "missing_credentials",
                "client_secret is required for the browser login flow.",
            )
        server, redirect_uri, result = create_callback_server(
            preferred_port, client_id=client_id, client_secret=client_secret
        )

    auth_url = build_auth_url(client_id, redirect_uri, scopes)

    print("\nOpening browser for authentication…", file=sys.stderr)
    opened = webbrowser.open(auth_url)
    if not opened:
        print(f"\nCould not open browser automatically. Visit:\n\n  {auth_url}\n", file=sys.stderr)
    else:
        print(f"Waiting for callback on {redirect_uri} …\n", file=sys.stderr)

    deadline = time.monotonic() + 300  # 5-minute wall-clock limit
    server.timeout = 2               # short poll so we can re-check deadline
    while not result.get("token_resp") and not result.get("oauth_error"):
        if time.monotonic() > deadline:
            break
        server.handle_request()
    server.server_close()

    if result.get("oauth_error"):
        utils.error_exit("oauth_exchange_failed", result["oauth_error"])

    token_resp = result.get("token_resp")
    code = result.get("code", "")
    accounts_server = result.get("accounts_server")

    if not token_resp and not code:
        utils.error_exit("oauth_timeout", "No authorisation code received. Did you approve access in the browser?")

    return redirect_uri, code, accounts_server, token_resp if isinstance(token_resp, dict) else None


# ── core OAuth helpers ────────────────────────────────────────────────────────

def build_auth_url(client_id: str, redirect_uri: str, scopes: list[str]) -> str:
    base = _config.accounts_base_url()
    params = {
        "scope": ",".join(scopes),
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "access_type": "offline",
        # prompt=consent forces Zoho to show the consent screen and re-issue a
        # refresh_token every time. Without this, Zoho skips the refresh_token
        # on subsequent logins because it considers the app already authorized.
        "prompt": "consent",
    }
    return f"{base}/oauth/v2/auth?{urlencode(params)}"


def parse_redirect(raw_url: str) -> tuple[str, Optional[str]]:
    """Parse code and optional regional accounts-server from a redirect URL."""
    try:
        parsed = urlparse(raw_url.strip())
        params = parse_qs(parsed.query)
        codes = params.get("code", [])
        if not codes:
            utils.error_exit("invalid_redirect_url", "Could not find 'code' in the pasted URL.")
        accounts_server = params.get("accounts-server", [None])[0]
        return codes[0], accounts_server
    except SystemExit:
        raise
    except Exception as exc:
        utils.error_exit("invalid_redirect_url", str(exc))
    return "", None  # unreachable


def try_exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    accounts_base_url: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Exchange code for tokens. Returns (data, None) or (None, error_message)."""
    base = (accounts_base_url or _config.accounts_base_url()).rstrip("/")
    logger.debug("Exchanging auth code via %s", base)
    resp = httpx.post(
        f"{base}/oauth/v2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text}"
    data = resp.json()
    if "access_token" not in data:
        return None, f"Unexpected response: {data}"
    return data, None


def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    accounts_base_url: Optional[str] = None,
) -> dict:
    data, err = try_exchange_code(
        code, client_id, client_secret, redirect_uri, accounts_base_url=accounts_base_url
    )
    if err:
        utils.error_exit("oauth_exchange_failed", err)
    return data  # type: ignore[return-value]


def refresh_access_token(
    email: str,
    client_id: str,
    client_secret: str,
    accounts_base_url: Optional[str] = None,
) -> str:
    token_data = storage.load_token(email)
    if not token_data:
        utils.error_exit(
            "not_logged_in",
            f"No stored token for {email}. Run: zoho login --account {email}",
        )

    base = (
        accounts_base_url
        or token_data.get("accounts_server")  # type: ignore[union-attr]
        or _config.accounts_base_url()
    ).rstrip("/")

    logger.debug("Refreshing access token for %s via %s", email, base)
    resp = httpx.post(
        f"{base}/oauth/v2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],  # type: ignore[index]
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        utils.error_exit("token_refresh_failed", f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if "access_token" not in data:
        utils.error_exit("token_refresh_failed", f"No access_token in response: {data}")
    return data["access_token"]


def discover_accounts_server(client_id: str) -> str:
    """Auto-detect the regional Zoho OAuth server by parallel-probing all regions.

    The correct server recognises the client_id and returns any error *except*
    ``invalid_client`` (typically ``invalid_code`` or ``invalid_grant``).
    Wrong servers don't know the client_id and return ``invalid_client``.
    Falls back to accounts.zoho.com if detection fails.
    """
    import concurrent.futures

    servers = [v[0] for v in _config.REGIONS.values()]
    probe_data = {
        "grant_type": "authorization_code",
        "code": "probe_x",
        "client_id": client_id,
        "client_secret": "probe_x",
        "redirect_uri": "https://probe.invalid/",
    }

    def _probe(server: str) -> Optional[str]:
        try:
            resp = httpx.post(
                f"{server}/oauth/v2/token",
                data=probe_data,
                timeout=8,
            )
            body = resp.json()
            if body.get("error") != "invalid_client":
                logger.debug("Region probe: %s → %s (match)", server, body.get("error"))
                return server
            logger.debug("Region probe: %s → invalid_client (no match)", server)
        except Exception as exc:
            logger.debug("Region probe failed for %s: %s", server, exc)
        return None

    futures: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(servers)) as ex:
        futures = {ex.submit(_probe, s): s for s in servers}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                return result

    logger.debug("Region auto-detection found no match; defaulting to accounts.zoho.com")
    return "https://accounts.zoho.com"


def discover_account_id(access_token: str, mail_base_url: Optional[str] = None) -> Optional[str]:
    base = (mail_base_url or _config.mail_base_url()).rstrip("/")
    logger.debug("Discovering accountId via %s", base)
    try:
        resp = httpx.get(
            f"{base}/accounts",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=15,
        )
        if resp.status_code == 200:
            accounts = resp.json().get("data", [])
            if accounts:
                return str(accounts[0].get("accountId", ""))
    except Exception as exc:
        logger.debug("accountId discovery failed: %s", exc)
    return None
