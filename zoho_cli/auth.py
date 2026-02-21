"""OAuth 2.0 helpers: login flow, token exchange, token refresh."""

import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from zoho_cli import config as _config
from zoho_cli import storage, utils

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = [
    "ZohoMail.messages.ALL",
    "ZohoMail.folders.ALL",
    "ZohoMail.accounts.READ",
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


# ── local callback server ─────────────────────────────────────────────────────

def _make_callback_handler(result: dict) -> type:
    """Return a request handler class that captures the OAuth code."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            accounts_server = params.get("accounts-server", [None])[0]

            if code:
                result["code"] = code
                result["accounts_server"] = accounts_server
                body = _SUCCESS_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code parameter.")

        def log_message(self, *args: object) -> None:
            pass  # suppress access logs

    return _Handler


def browser_login_flow(
    client_id: str,
    scopes: list[str],
    preferred_port: int = 51821,
) -> tuple[str, str, Optional[str]]:
    """
    Open the browser, spin up a local server, wait for the OAuth callback.
    Returns (redirect_uri, code, accounts_server).
    """
    import webbrowser

    result: dict = {}
    handler_cls = _make_callback_handler(result)

    # Bind server — preferred port first, then let OS pick
    try:
        server = HTTPServer(("localhost", preferred_port), handler_cls)
        actual_port = preferred_port
    except OSError:
        server = HTTPServer(("localhost", 0), handler_cls)
        actual_port = server.server_address[1]

    redirect_uri = f"http://localhost:{actual_port}/callback"
    auth_url = build_auth_url(client_id, redirect_uri, scopes)

    print("\nOpening browser for authentication…", file=sys.stderr)
    opened = webbrowser.open(auth_url)
    if not opened:
        print(f"\nCould not open browser automatically. Visit:\n\n  {auth_url}\n", file=sys.stderr)
    else:
        print(f"Waiting for callback on {redirect_uri} …\n", file=sys.stderr)

    # Loop until we receive the request that contains the OAuth code.
    # A single handle_request() is not enough: browsers often fire
    # additional requests (favicon, preflight, etc.) before the real
    # callback arrives, which would consume the one-shot slot and leave
    # the server closed when the actual redirect comes in.
    import time
    deadline = time.monotonic() + 300  # 5-minute wall-clock limit
    server.timeout = 2  # short select() interval so we can check deadline
    while not result.get("code"):
        if time.monotonic() > deadline:
            break
        server.handle_request()
    server.server_close()

    code = result.get("code", "")
    accounts_server = result.get("accounts_server")

    if not code:
        utils.error_exit("oauth_timeout", "No authorisation code received. Did you approve access in the browser?")

    return redirect_uri, code, accounts_server


# ── core OAuth helpers ────────────────────────────────────────────────────────

def build_auth_url(client_id: str, redirect_uri: str, scopes: list[str]) -> str:
    base = _config.accounts_base_url()
    params = {
        "scope": ",".join(scopes),
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "access_type": "offline",
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


def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    accounts_base_url: Optional[str] = None,
) -> dict:
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
        utils.error_exit("oauth_exchange_failed", f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    if "access_token" not in data:
        utils.error_exit("oauth_exchange_failed", f"Unexpected response: {data}")
    return data


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
