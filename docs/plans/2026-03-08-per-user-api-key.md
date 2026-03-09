# Per-User API Key Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `SURE_API_KEY` from server-side environment config to per-user HTTP request headers, so each Claude client connecting to the shared SSE server authenticates with their own Sure account.

**Architecture:** A Starlette middleware layer reads `X-Sure-Api-Key` from every incoming HTTP request header and stores it in a Python `ContextVar`. All tool functions read from the `ContextVar` first, falling back to `os.getenv()` so local/stdio mode stays unchanged.

**Tech Stack:** Python 3.12, FastMCP (Starlette/ASGI under the hood), `contextvars.ContextVar`, `pytest`, `httpx` (for test client).

---

### Task 1: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_middleware.py`

**Step 1: Install dev dependencies**

```bash
pip install -e ".[dev]"
```

Expected: no errors, `pytest` available.

**Step 2: Create the tests package**

Create `tests/__init__.py` as an empty file.

**Step 3: Write a failing test for the middleware — header present**

Create `tests/test_middleware.py`:

```python
"""Tests for per-user API key middleware."""
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def test_middleware_sets_api_key_when_header_present():
    """Middleware should set _api_key_var when X-Sure-Api-Key header is provided."""
    from sure_mcp_server.server import ApiKeyMiddleware, _api_key_var

    captured = {}

    async def endpoint(request: Request) -> JSONResponse:
        captured["key"] = _api_key_var.get()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/test", endpoint)])
    app.add_middleware(ApiKeyMiddleware)

    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/test", headers={"X-Sure-Api-Key": "my-test-key"})

    assert response.status_code == 200
    assert captured["key"] == "my-test-key"


def test_middleware_returns_403_when_header_missing():
    """Middleware should return 403 when X-Sure-Api-Key header is absent."""
    from sure_mcp_server.server import ApiKeyMiddleware

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/test", endpoint)])
    app.add_middleware(ApiKeyMiddleware)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test")

    assert response.status_code == 403
    assert "X-Sure-Api-Key" in response.json()["error"]
```

**Step 4: Run the test to confirm it fails**

```bash
pytest tests/test_middleware.py -v
```

Expected: `ImportError` or `AttributeError` — `ApiKeyMiddleware` and `_api_key_var` don't exist yet.

---

### Task 2: Add `ContextVar` and `ApiKeyMiddleware` to `server.py`

**Files:**
- Modify: `src/sure_mcp_server/server.py`

**Step 1: Add imports at the top of `server.py`** (after existing imports)

```python
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
```

**Step 2: Add the `ContextVar` and middleware class** (after `mcp = FastMCP("Sure MCP Server")`)

```python
# Per-request API key (set by middleware from X-Sure-Api-Key header)
_api_key_var: ContextVar[str | None] = ContextVar("api_key", default=None)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Extract X-Sure-Api-Key header and store it in _api_key_var for each request."""

    async def dispatch(self, request: StarletteRequest, call_next):
        api_key = request.headers.get("X-Sure-Api-Key")
        if not api_key:
            return JSONResponse(
                {"error": "Missing X-Sure-Api-Key header. Add it to your Claude MCP config under 'headers'."},
                status_code=403,
            )
        token = _api_key_var.set(api_key)
        try:
            return await call_next(request)
        finally:
            _api_key_var.reset(token)
```

**Step 3: Mount the middleware onto FastMCP's Starlette app** (after the middleware class definition)

```python
# Only add middleware when running in SSE/HTTP mode (app attribute exists)
if hasattr(mcp, "app"):
    mcp.app.add_middleware(ApiKeyMiddleware)
```

**Step 4: Run middleware tests — they should pass now**

```bash
pytest tests/test_middleware.py -v
```

Expected: both tests PASS.

**Step 5: Commit**

```bash
git add src/sure_mcp_server/server.py tests/__init__.py tests/test_middleware.py
git commit -m "feat: add ApiKeyMiddleware to capture per-user X-Sure-Api-Key header"
```

---

### Task 3: Update `get_auth_header()` to read from `ContextVar`

**Files:**
- Modify: `src/sure_mcp_server/server.py:31-41`
- Modify: `tests/test_middleware.py` (add new tests)

**Step 1: Write failing tests for `get_auth_header()`**

Add to `tests/test_middleware.py`:

```python
def test_get_auth_header_reads_from_context_var():
    """get_auth_header() should use _api_key_var when set."""
    from sure_mcp_server.server import get_auth_header, _api_key_var

    token = _api_key_var.set("ctx-key-123")
    try:
        headers = get_auth_header()
    finally:
        _api_key_var.reset(token)

    assert headers == {"X-Api-Key": "ctx-key-123"}


def test_get_auth_header_falls_back_to_env(monkeypatch):
    """get_auth_header() should fall back to SURE_API_KEY env var when ContextVar is not set."""
    from sure_mcp_server.server import get_auth_header, _api_key_var

    # Ensure ContextVar is not set
    _api_key_var.set(None)
    monkeypatch.setenv("SURE_API_KEY", "env-key-456")

    headers = get_auth_header()
    assert headers == {"X-Api-Key": "env-key-456"}


def test_get_auth_header_raises_when_nothing_configured(monkeypatch):
    """get_auth_header() should raise RuntimeError when neither ContextVar nor env is set."""
    from sure_mcp_server.server import get_auth_header, _api_key_var

    _api_key_var.set(None)
    monkeypatch.delenv("SURE_API_KEY", raising=False)
    monkeypatch.delenv("SURE_ACCESS_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="No authentication configured"):
        get_auth_header()
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_middleware.py::test_get_auth_header_reads_from_context_var -v
```

Expected: FAIL — current `get_auth_header()` doesn't read from `_api_key_var`.

**Step 3: Update `get_auth_header()` in `server.py`**

Replace the existing function:

```python
def get_auth_header() -> Dict[str, str]:
    """Get authentication header for API requests.

    Reads from per-request ContextVar first (SSE mode, set by ApiKeyMiddleware),
    then falls back to environment variables (local/stdio mode).
    """
    api_key = _api_key_var.get() or os.getenv("SURE_API_KEY")
    access_token = os.getenv("SURE_ACCESS_TOKEN")

    if api_key:
        return {"X-Api-Key": api_key}
    elif access_token:
        return {"Authorization": f"Bearer {access_token}"}
    else:
        raise RuntimeError(
            "❌ No authentication configured. "
            "In SSE mode: add 'X-Sure-Api-Key' to your Claude MCP config headers. "
            "In local mode: set SURE_API_KEY in your environment."
        )
```

**Step 4: Run all tests**

```bash
pytest tests/test_middleware.py -v
```

Expected: all 5 tests PASS.

**Step 5: Commit**

```bash
git add src/sure_mcp_server/server.py tests/test_middleware.py
git commit -m "feat: get_auth_header reads from ContextVar with env var fallback"
```

---

### Task 4: Update `docker-compose.yml` and `.env.example`

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Step 1: Remove `SURE_API_KEY` from `docker-compose.yml`**

In the `environment:` section, delete:
```yaml
      - SURE_API_KEY=${SURE_API_KEY}
```

**Step 2: Update `.env.example`**

Replace:
```
SURE_API_URL=http://localhost:3000
SURE_API_KEY=
SURE_ACCESS_TOKEN=
SURE_REFRESH_TOKEN=
SURE_TIMEOUT=30
# SURE_VERIFY_SSL=false
SURE_VERIFY_SSL=true
```

With:
```
# Sure MCP Server - Environment Variables
# These are SERVER-SIDE settings (same for all users).
# Each user's API key is passed via their Claude MCP config headers, not here.

SURE_API_URL=http://localhost:3000
SURE_TIMEOUT=30
# SURE_VERIFY_SSL=false  # Set to false for local Docker where Sure has no TLS
SURE_VERIFY_SSL=true

# Local/stdio mode only (not needed for SSE/NAS mode):
# SURE_API_KEY=your-api-key-here
# SURE_ACCESS_TOKEN=
```

**Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "chore: remove SURE_API_KEY from server config (now per-user via headers)"
```

---

### Task 5: Update `setup_authentication` tool and `check_auth_status`

**Files:**
- Modify: `src/sure_mcp_server/server.py:76-130`

**Step 1: Replace the `setup_authentication` tool text**

```python
@mcp.tool()
def setup_authentication() -> str:
    """Get instructions for setting up authentication with Sure."""
    return """🔐 Sure MCP Server - Setup Instructions

━━━ SSE / Shared Server Mode (NAS deployment) ━━━

1️⃣ Get your personal Sure API key:
   • Log into Sure at your Sure instance URL
   • Go to Settings > API Key and generate a new key

2️⃣ Add to your Claude Desktop config:
   "mcpServers": {
     "Sure": {
       "url": "http://<nas-ip>:8765/sse",
       "headers": {
         "X-Sure-Api-Key": "your-personal-api-key-here"
       }
     }
   }

3️⃣ Restart Claude Desktop

━━━ Local / Docker stdio Mode ━━━

1️⃣ Build the image: docker compose build

2️⃣ Add to your Claude Desktop config:
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

3️⃣ Restart Claude Desktop

✅ Test with: check_connection"""
```

**Step 2: Update `check_auth_status` to reflect new logic**

```python
@mcp.tool()
def check_auth_status() -> str:
    """Check if authentication is configured for Sure API."""
    try:
        api_url = os.getenv("SURE_API_URL")
        ctx_key = _api_key_var.get()
        env_key = os.getenv("SURE_API_KEY")
        access_token = os.getenv("SURE_ACCESS_TOKEN")

        status = ""

        if api_url:
            status += f"✅ API URL: {api_url}\n"
        else:
            status += "❌ SURE_API_URL not configured on server\n"

        if ctx_key:
            status += "✅ API Key: provided via X-Sure-Api-Key header (SSE mode)\n"
        elif env_key:
            status += "✅ API Key: provided via SURE_API_KEY env var (local mode)\n"
        elif access_token:
            status += "✅ Access Token: provided via SURE_ACCESS_TOKEN env var\n"
        else:
            status += (
                "❌ No API key configured.\n"
                "   SSE mode: add X-Sure-Api-Key to your Claude MCP config headers.\n"
                "   Local mode: set SURE_API_KEY in your Claude MCP config env.\n"
            )

        status += "\n💡 Try check_connection to test the full API connection."
        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"
```

**Step 3: Commit**

```bash
git add src/sure_mcp_server/server.py
git commit -m "feat: update setup_authentication and check_auth_status for per-user key"
```

---

### Task 6: Update README

**Files:**
- Modify: `README.md`

**Step 1: Update the SSE/Docker Option A section**

Replace the Claude Desktop config block in Option A with:

```json
{
  "mcpServers": {
    "Sure": {
      "url": "http://<nas-ip>:8765/sse",
      "headers": {
        "X-Sure-Api-Key": "your-personal-api-key-here"
      }
    }
  }
}
```

Add a note above it:
> **Note:** In SSE mode, each user provides their own API key via the `headers` field — no key is stored on the server.

Keep the existing `env`-based config block for local Docker (stdio) mode as a separate option.

Update the Configuration table to note:

| Variable | Required | Where | Description |
|----------|----------|-------|-------------|
| `SURE_API_URL` | Yes | Server `.env` | Base URL of your Sure instance |
| `SURE_API_KEY` | Yes | Claude config `headers` (SSE) or `env` (local) | Your personal Sure API key |
| `SURE_TIMEOUT` | No | Server `.env` | Request timeout in seconds (default: 30) |
| `SURE_VERIFY_SSL` | No | Server `.env` | Verify SSL certificates (default: true) |

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README for per-user API key via headers in SSE mode"
```

---

### Task 7: Final verification

**Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests PASS.

**Step 2: Quick smoke test — middleware blocks missing key**

```bash
# Start server in background
python -m sure_mcp_server.server &

# Should return 403
curl -s http://localhost:8765/sse | head -5

# Should return 200 (SSE stream starts)
curl -s -H "X-Sure-Api-Key: test-key" http://localhost:8765/sse &
sleep 1
kill %2 %1
```

**Step 3: Push the branch**

```bash
git push -u origin feature/per-user-api-key
```
