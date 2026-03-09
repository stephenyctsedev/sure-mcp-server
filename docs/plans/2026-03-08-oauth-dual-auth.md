# OAuth Dual-Auth Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OAuth 2.0 Authorization Code flow so Claude.ai web users authenticate with their own Sure API key, while preserving `X-Sure-Api-Key` header support for Claude Desktop users.

**Architecture:** Three new components — `AuthDB` (SQLite token store), `oauth_routes.py` (3 Starlette routes), and `AuthMiddleware` (replaces old middleware, handles Bearer token → X-Sure-Api-Key header → env var fallback). All paths set the same `ContextVar` so tool code is untouched.

**Tech Stack:** Python 3.12, FastMCP (Starlette/ASGI), stdlib `sqlite3`, `secrets`, Starlette `TestClient` (via `httpx` already in deps), `pytest`.

---

### Task 1: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_auth_db.py`

**Step 1: Install dev dependencies**

```bash
pip install -e ".[dev]"
```

Expected: no errors.

**Step 2: Create the tests package**

Create `tests/__init__.py` as an empty file.

**Step 3: Write failing tests for `AuthDB`**

Create `tests/test_auth_db.py`:

```python
"""Tests for AuthDB SQLite token store."""
import sqlite3
import time
import pytest
from sure_mcp_server.auth_db import AuthDB


@pytest.fixture
def db(tmp_path):
    d = AuthDB(str(tmp_path / "test.db"))
    d.initialize()
    return d


def test_create_and_exchange_code(db):
    code = db.create_auth_code("my-api-key", "state123")
    assert len(code) == 64  # secrets.token_hex(32) = 64 hex chars
    api_key = db.exchange_code(code)
    assert api_key == "my-api-key"


def test_code_is_single_use(db):
    code = db.create_auth_code("key", "state")
    db.exchange_code(code)
    assert db.exchange_code(code) is None


def test_expired_code_returns_none(db):
    code = db.create_auth_code("key", "state")
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE auth_codes SET expires_at = ? WHERE code = ?",
            (int(time.time()) - 1, code)
        )
    assert db.exchange_code(code) is None


def test_create_and_lookup_token(db):
    token = db.create_token("my-api-key")
    assert len(token) == 64
    assert db.get_api_key_for_token(token) == "my-api-key"


def test_unknown_token_returns_none(db):
    assert db.get_api_key_for_token("nonexistent") is None
```

**Step 4: Run to confirm they fail**

```bash
pytest tests/test_auth_db.py -v
```

Expected: `ImportError` — `sure_mcp_server.auth_db` doesn't exist yet.

---

### Task 2: Implement `AuthDB`

**Files:**
- Create: `src/sure_mcp_server/auth_db.py`

**Step 1: Create `auth_db.py`**

```python
"""SQLite-backed store for OAuth auth codes and access tokens."""
import os
import secrets
import sqlite3
import time
from pathlib import Path


class AuthDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AUTH_DB_PATH", "/app/data/auth.db")

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code       TEXT PRIMARY KEY,
                    api_key    TEXT NOT NULL,
                    state      TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    token      TEXT PRIMARY KEY,
                    api_key    TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)

    def create_auth_code(self, api_key: str, state: str) -> str:
        """Generate a single-use auth code valid for 10 minutes."""
        code = secrets.token_hex(32)
        expires_at = int(time.time()) + 600
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_codes VALUES (?, ?, ?, ?)",
                (code, api_key, state, expires_at),
            )
        return code

    def exchange_code(self, code: str) -> str | None:
        """Exchange auth code for api_key. Deletes code (single use). Returns None if invalid/expired."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM auth_codes WHERE expires_at < ?", (int(time.time()),)
            )
            row = conn.execute(
                "SELECT api_key FROM auth_codes WHERE code = ?", (code,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM auth_codes WHERE code = ?", (code,))
                return row[0]
        return None

    def create_token(self, api_key: str) -> str:
        """Issue a long-lived access token for an api_key."""
        token = secrets.token_hex(32)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tokens VALUES (?, ?, ?)",
                (token, api_key, int(time.time())),
            )
        return token

    def get_api_key_for_token(self, token: str) -> str | None:
        """Look up the api_key for a Bearer token. Returns None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT api_key FROM tokens WHERE token = ?", (token,)
            ).fetchone()
        return row[0] if row else None
```

**Step 2: Run tests**

```bash
pytest tests/test_auth_db.py -v
```

Expected: all 5 tests PASS.

**Step 3: Commit**

```bash
git add src/sure_mcp_server/auth_db.py tests/__init__.py tests/test_auth_db.py
git commit -m "feat: add AuthDB SQLite token store"
```

---

### Task 3: Implement OAuth routes

**Files:**
- Create: `src/sure_mcp_server/oauth_routes.py`
- Create: `tests/test_oauth_routes.py`

**Step 1: Write failing tests**

Create `tests/test_oauth_routes.py`:

```python
"""Tests for OAuth 2.0 routes."""
from urllib.parse import parse_qs, urlparse
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from sure_mcp_server.auth_db import AuthDB
from sure_mcp_server.oauth_routes import make_oauth_routes


@pytest.fixture
def client_and_db(tmp_path):
    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    routes = make_oauth_routes(db, "https://example.com")
    app = Starlette(routes=routes)
    return TestClient(app, raise_server_exceptions=True), db


def test_discovery_returns_endpoints(client_and_db):
    client, _ = client_and_db
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["authorization_endpoint"] == "https://example.com/authorize"
    assert data["token_endpoint"] == "https://example.com/token"


def test_authorize_get_returns_form(client_and_db):
    client, _ = client_and_db
    response = client.get(
        "/authorize",
        params={"state": "abc", "redirect_uri": "https://claude.ai/callback", "client_id": "X-Sure-Api-Key"},
    )
    assert response.status_code == 200
    assert "Sure API Key" in response.text
    assert 'name="api_key"' in response.text


def test_full_oauth_flow(client_and_db):
    client, db = client_and_db
    # POST authorize
    response = client.post(
        "/authorize",
        data={
            "api_key": "my-sure-key",
            "redirect_uri": "https://claude.ai/callback",
            "state": "xyz",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "client_id": "X-Sure-Api-Key",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    code = parse_qs(urlparse(location).query)["code"][0]

    # POST token
    response = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert db.get_api_key_for_token(data["access_token"]) == "my-sure-key"


def test_token_with_invalid_code_returns_400(client_and_db):
    client, _ = client_and_db
    response = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": "bad-code"},
    )
    assert response.status_code == 400


def test_missing_api_key_returns_400(client_and_db):
    client, _ = client_and_db
    response = client.post(
        "/authorize",
        data={"redirect_uri": "https://claude.ai/callback", "state": "xyz", "api_key": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_oauth_routes.py -v
```

Expected: `ImportError` — `oauth_routes` doesn't exist yet.

**Step 3: Create `oauth_routes.py`**

```python
"""OAuth 2.0 Authorization Code routes for Claude.ai web connector support."""
import html
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route
from sure_mcp_server.auth_db import AuthDB


def make_oauth_routes(auth_db: AuthDB, base_url: str) -> list:
    """Return list of Starlette Routes for OAuth 2.0 endpoints."""

    async def discovery(request: Request) -> JSONResponse:
        return JSONResponse({
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/authorize",
            "token_endpoint": f"{base_url}/token",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
        })

    async def authorize(request: Request) -> HTMLResponse | RedirectResponse:
        if request.method == "GET":
            return _authorize_form(request)
        return await _authorize_submit(request, auth_db)

    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        if form.get("grant_type") != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        code = form.get("code", "")
        api_key = auth_db.exchange_code(code)
        if not api_key:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        access_token = auth_db.create_token(api_key)
        return JSONResponse({"access_token": access_token, "token_type": "bearer"})

    return [
        Route("/.well-known/oauth-authorization-server", discovery),
        Route("/authorize", authorize, methods=["GET", "POST"]),
        Route("/token", token, methods=["POST"]),
    ]


def _authorize_form(request: Request) -> HTMLResponse:
    params = request.query_params

    def h(key: str) -> str:
        return html.escape(params.get(key, ""), quote=True)

    form_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Connect Sure Finance</title>
  <style>
    body {{ font-family: sans-serif; max-width: 420px; margin: 60px auto; padding: 0 20px; }}
    input[type=password] {{ width: 100%; padding: 8px; margin: 8px 0 16px; box-sizing: border-box; }}
    button {{ padding: 10px 24px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }}
  </style>
</head>
<body>
  <h2>Connect Sure Finance</h2>
  <p>Enter your personal Sure API key to connect your account.</p>
  <form method="post" action="/authorize">
    <input type="hidden" name="redirect_uri" value="{h('redirect_uri')}">
    <input type="hidden" name="state" value="{h('state')}">
    <input type="hidden" name="code_challenge" value="{h('code_challenge')}">
    <input type="hidden" name="code_challenge_method" value="{h('code_challenge_method')}">
    <input type="hidden" name="client_id" value="{h('client_id')}">
    <label for="api_key">Sure API Key:</label>
    <input type="password" id="api_key" name="api_key" autofocus placeholder="Paste your API key here">
    <button type="submit">Connect</button>
  </form>
  <p><small>Get your API key from Sure: Settings &gt; API Key</small></p>
</body>
</html>"""
    return HTMLResponse(form_html)


async def _authorize_submit(request: Request, auth_db: AuthDB) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    api_key = str(form.get("api_key", "")).strip()
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))

    if not api_key:
        return HTMLResponse("API key is required.", status_code=400)
    if not redirect_uri:
        return HTMLResponse("redirect_uri is required.", status_code=400)

    code = auth_db.create_auth_code(api_key, state)
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)
```

**Step 4: Run tests**

```bash
pytest tests/test_oauth_routes.py -v
```

Expected: all 5 tests PASS.

**Step 5: Commit**

```bash
git add src/sure_mcp_server/oauth_routes.py tests/test_oauth_routes.py
git commit -m "feat: add OAuth 2.0 authorization routes"
```

---

### Task 4: Implement `AuthMiddleware` in `server.py`

**Files:**
- Modify: `src/sure_mcp_server/server.py`
- Create: `tests/test_middleware.py`

**Step 1: Write failing tests**

Create `tests/test_middleware.py`:

```python
"""Tests for AuthMiddleware."""
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from sure_mcp_server.auth_db import AuthDB


def make_test_app(tmp_path, extra_env=None, monkeypatch=None):
    from sure_mcp_server.server import AuthMiddleware, _api_key_var

    captured = {}

    async def endpoint(request: Request) -> JSONResponse:
        captured["key"] = _api_key_var.get()
        return JSONResponse({"ok": True})

    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    app = Starlette(routes=[Route("/test", endpoint)])
    app.add_middleware(AuthMiddleware, auth_db=db)
    return TestClient(app, raise_server_exceptions=False), db, captured


def test_bearer_token_sets_api_key(tmp_path):
    client, db, captured = make_test_app(tmp_path)
    token = db.create_token("bearer-key")
    response = client.get("/test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert captured["key"] == "bearer-key"


def test_x_sure_api_key_header_sets_api_key(tmp_path):
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test", headers={"X-Sure-Api-Key": "header-key"})
    assert response.status_code == 200
    assert captured["key"] == "header-key"


def test_env_var_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SURE_API_KEY", "env-key")
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test")
    assert response.status_code == 200
    assert captured["key"] == "env-key"


def test_no_auth_returns_403(tmp_path, monkeypatch):
    monkeypatch.delenv("SURE_API_KEY", raising=False)
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test")
    assert response.status_code == 403


def test_oauth_paths_bypass_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("SURE_API_KEY", raising=False)
    from sure_mcp_server.server import AuthMiddleware

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    app = Starlette(routes=[
        Route("/.well-known/oauth-authorization-server", endpoint),
        Route("/authorize", endpoint, methods=["GET", "POST"]),
        Route("/token", endpoint, methods=["POST"]),
    ])
    app.add_middleware(AuthMiddleware, auth_db=db)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
    assert client.get("/authorize").status_code == 200
    assert client.post("/token", data={}).status_code == 200
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_middleware.py -v
```

Expected: `ImportError` — `AuthMiddleware` doesn't exist yet.

**Step 3: Add imports and `ContextVar` to `server.py`**

At the top of `server.py`, add to the import block:

```python
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSONResponse
```

After `mcp = FastMCP("Sure MCP Server")`, add:

```python
# Per-request API key (set by AuthMiddleware from OAuth Bearer token or X-Sure-Api-Key header)
_api_key_var: ContextVar[str | None] = ContextVar("api_key", default=None)
```

**Step 4: Add `AuthMiddleware` class** (after `_api_key_var`)

```python
class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate each request via Bearer token (OAuth), X-Sure-Api-Key header, or env var fallback."""

    OAUTH_PATHS = frozenset(["/authorize", "/token", "/.well-known/oauth-authorization-server"])

    def __init__(self, app, auth_db) -> None:
        super().__init__(app)
        self.auth_db = auth_db

    async def dispatch(self, request: StarletteRequest, call_next):
        if request.url.path in self.OAUTH_PATHS:
            return await call_next(request)

        api_key: str | None = None

        # 1. OAuth Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = self.auth_db.get_api_key_for_token(auth_header[7:])

        # 2. X-Sure-Api-Key header (Claude Desktop)
        if not api_key:
            api_key = request.headers.get("X-Sure-Api-Key")

        # 3. Env var fallback (local/stdio mode)
        if not api_key:
            api_key = os.getenv("SURE_API_KEY")

        if not api_key:
            return StarletteJSONResponse(
                {
                    "error": (
                        "Authentication required. "
                        "Claude.ai web: connect via the custom connector URL (OAuth). "
                        "Claude Desktop: add X-Sure-Api-Key to your MCP config headers."
                    )
                },
                status_code=403,
            )

        token = _api_key_var.set(api_key)
        try:
            return await call_next(request)
        finally:
            _api_key_var.reset(token)
```

**Step 5: Update `get_auth_header()` to read from `_api_key_var`**

Replace the existing `get_auth_header()` function:

```python
def get_auth_header() -> Dict[str, str]:
    """Get authentication header. Reads ContextVar (SSE mode) then env var (local mode)."""
    api_key = _api_key_var.get() or os.getenv("SURE_API_KEY")
    access_token = os.getenv("SURE_ACCESS_TOKEN")

    if api_key:
        return {"X-Api-Key": api_key}
    elif access_token:
        return {"Authorization": f"Bearer {access_token}"}
    else:
        raise RuntimeError(
            "❌ No authentication configured. "
            "Claude.ai web: use OAuth (add the connector URL). "
            "Claude Desktop: add X-Sure-Api-Key to your MCP config headers. "
            "Local mode: set SURE_API_KEY in your environment."
        )
```

**Step 6: Run all middleware tests**

```bash
pytest tests/test_middleware.py -v
```

Expected: all 5 tests PASS.

**Step 7: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

**Step 8: Commit**

```bash
git add src/sure_mcp_server/server.py tests/test_middleware.py
git commit -m "feat: add AuthMiddleware with OAuth Bearer, header, and env var fallback"
```

---

### Task 5: Wire OAuth into `main()`

**Files:**
- Modify: `src/sure_mcp_server/server.py:529-547`

**Step 1: Update `main()` to initialise `AuthDB`, mount OAuth routes, and add middleware**

Replace the existing `main()` function:

```python
def main():
    """Main entry point for the server."""
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8765"))
    base_url = os.getenv("MCP_BASE_URL", f"http://localhost:{port}").rstrip("/")

    logger.info(f"Starting Sure MCP Server (SSE) on {host}:{port}...")
    logger.info(f"OAuth base URL: {base_url}")

    # Initialise SQLite auth store
    from sure_mcp_server.auth_db import AuthDB
    from sure_mcp_server.oauth_routes import make_oauth_routes

    auth_db = AuthDB()
    auth_db.initialize()

    # Configure and start FastMCP
    mcp.settings.host = host
    mcp.settings.port = port

    # Add OAuth routes and AuthMiddleware to FastMCP's Starlette app
    # mcp.app is the underlying Starlette application
    for route in make_oauth_routes(auth_db, base_url):
        mcp.app.router.routes.insert(0, route)
    mcp.app.add_middleware(AuthMiddleware, auth_db=auth_db)

    try:
        mcp.run(transport="sse")
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise
```

> **Note for implementer:** If `mcp.app.router.routes.insert(0, route)` doesn't work (Starlette may not pick up dynamically-added routes after app creation), the fallback is to build a combined Starlette app manually:
>
> ```python
> from starlette.applications import Starlette
> from starlette.routing import Mount
> import uvicorn
>
> oauth_routes = make_oauth_routes(auth_db, base_url)
> combined = Starlette(routes=oauth_routes + [Mount("/", app=mcp.app)])
> combined.add_middleware(AuthMiddleware, auth_db=auth_db)
> uvicorn.run(combined, host=host, port=port)
> ```
>
> Try the first approach; use this fallback if the server starts but `/authorize` returns 404.

**Step 2: Start the server and verify OAuth endpoints respond**

```bash
python -m sure_mcp_server.server &
sleep 2

# Should return JSON with authorize/token URLs
curl -s http://localhost:8765/.well-known/oauth-authorization-server | python -m json.tool

# Should return HTML form
curl -s "http://localhost:8765/authorize?state=test&redirect_uri=https://example.com/callback&client_id=X-Sure-Api-Key" | grep "Sure API Key"

# Should return 403 (no auth)
curl -s http://localhost:8765/sse | python -m json.tool

kill %1
```

Expected:
- Discovery returns JSON with correct URLs
- `/authorize` returns HTML containing "Sure API Key"
- `/sse` without auth returns 403

**Step 3: Commit**

```bash
git add src/sure_mcp_server/server.py
git commit -m "feat: wire OAuth routes and AuthMiddleware into server main()"
```

---

### Task 6: Update `docker-compose.yml` and `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Step 1: Update `docker-compose.yml`**

Replace the full file content:

```yaml
services:
  sure-mcp-server:
    build: .
    image: sure-mcp-server:latest
    container_name: sure-mcp-server
    ports:
      - "8765:8765"
    environment:
      - SURE_API_URL=${SURE_API_URL:-http://host.docker.internal:3000}
      - SURE_TIMEOUT=${SURE_TIMEOUT:-30}
      - SURE_VERIFY_SSL=${SURE_VERIFY_SSL:-false}
      - MCP_HOST=0.0.0.0
      - MCP_PORT=8765
      - MCP_BASE_URL=${MCP_BASE_URL:-http://localhost:8765}
    volumes:
      - sure-mcp-data:/app/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped

volumes:
  sure-mcp-data:
```

**Step 2: Update `.env.example`**

```
# Sure MCP Server - Server-side configuration
# Each user's API key is handled via OAuth (Claude.ai web) or X-Sure-Api-Key header (Claude Desktop).
# No SURE_API_KEY needed here.

SURE_API_URL=http://localhost:9000
SURE_VERIFY_SSL=false
MCP_BASE_URL=https://your-public-domain.example.com

# Optional overrides
# SURE_TIMEOUT=30
# MCP_HOST=0.0.0.0
# MCP_PORT=8765

# Local/stdio mode only (single user, not needed for SSE/NAS):
# SURE_API_KEY=your-api-key-here
```

**Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: add MCP_BASE_URL and auth volume to docker-compose"
```

---

### Task 7: Update `setup_authentication` tool and README

**Files:**
- Modify: `src/sure_mcp_server/server.py` (setup_authentication tool)
- Modify: `README.md`

**Step 1: Replace `setup_authentication` tool text** (lines ~76-100 in server.py)

```python
@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up authentication with Sure."""
    return """🔐 Sure MCP Server - Setup Instructions

━━━ Claude.ai Web (OAuth) ━━━

1️⃣ Get your Sure API key:
   • Log into Sure → Settings → API Key → Generate

2️⃣ In Claude.ai, go to Settings → Connectors → Add custom connector
   • Name: Sure Finance
   • URL: https://<your-server>/sse
   • Click Add — you'll be redirected to a login page

3️⃣ Enter your Sure API key in the browser form

4️⃣ Done — each user authenticates with their own key

━━━ Claude Desktop (header) ━━━

Add to your Claude Desktop config:
   "mcpServers": {
     "Sure": {
       "url": "https://<your-server>/sse",
       "headers": {
         "X-Sure-Api-Key": "your-personal-api-key"
       }
     }
   }

━━━ Local Docker (single user) ━━━

   "mcpServers": {
     "Sure": {
       "command": "docker",
       "args": ["run", "-i", "--rm",
                "-e", "SURE_API_URL", "-e", "SURE_API_KEY",
                "--add-host=host.docker.internal:host-gateway",
                "sure-mcp-server"],
       "env": {
         "SURE_API_URL": "http://host.docker.internal:3000",
         "SURE_API_KEY": "your-api-key-here",
         "SURE_VERIFY_SSL": "false"
       }
     }
   }

✅ Test connection with: check_connection"""
```

**Step 2: Update README.md — replace Quick Start section**

Update the three options to match the new auth design:

- **Option A (SSE/shared)**: show Claude.ai connector URL only (no headers — OAuth handles it). Add note about MCP_BASE_URL.
- **Option B (Claude Desktop)**: show `headers: { "X-Sure-Api-Key": "..." }` with SSE URL.
- **Option C (Local Docker)**: keep existing `env` config unchanged.

Update the Configuration table:

| Variable | Required | Where | Description |
|----------|----------|-------|-------------|
| `SURE_API_URL` | Yes | Server `.env` | Base URL of your Sure instance |
| `MCP_BASE_URL` | Yes (SSE mode) | Server `.env` | Public URL of this server (used in OAuth) |
| `SURE_API_KEY` | No | Client `env` (local only) | API key for local/stdio mode only |
| `SURE_TIMEOUT` | No | Server `.env` | Request timeout in seconds (default: 30) |
| `SURE_VERIFY_SSL` | No | Server `.env` | Verify SSL certificates (default: true) |

**Step 3: Run all tests one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

**Step 4: Commit**

```bash
git add src/sure_mcp_server/server.py README.md
git commit -m "docs: update setup_authentication tool and README for OAuth dual-auth"
```

---

### Task 8: Final verification and push

**Step 1: Build Docker image**

```bash
docker compose build
```

Expected: builds successfully.

**Step 2: Start server with a test `.env`**

```bash
MCP_BASE_URL=http://localhost:8765 SURE_API_URL=http://localhost:9000 docker compose up -d
sleep 3
```

**Step 3: Smoke test all three endpoints**

```bash
# OAuth discovery
curl -s http://localhost:8765/.well-known/oauth-authorization-server | python -m json.tool

# OAuth form
curl -s "http://localhost:8765/authorize?state=x&redirect_uri=https://claude.ai/api/mcp/auth_callback&client_id=X-Sure-Api-Key" | grep "Sure API Key"

# Unauth request returns 403
curl -s http://localhost:8765/sse
```

Expected:
1. Discovery JSON with correct URLs
2. HTML form with "Sure API Key" label
3. 403 JSON error message

**Step 4: Clean up**

```bash
docker compose down
```

**Step 5: Push branch**

```bash
git push origin feature/oauth-dual-auth
```
