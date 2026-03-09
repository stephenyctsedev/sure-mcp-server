# Per-User API Key Design

**Date:** 2026-03-08
**Branch:** `feature/per-user-api-key`
**Status:** Approved

## Problem

When running the Sure MCP Server in SSE/HTTP transport mode (shared NAS deployment), the `SURE_API_KEY` is baked into the server's `.env` and `docker-compose.yml`. This means all connecting Claude clients share a single Sure account, which is wrong for a multi-user deployment.

## Context

- Multiple users each have their own Sure account API key.
- All users share one Sure server (`SURE_API_URL` is the same for everyone).
- The MCP server runs in SSE HTTP mode on a NAS; users connect remotely.
- Local/stdio/Docker-run mode must continue to work unchanged (backward compat).

## Decision

**Option A — HTTP headers per SSE connection.**

Each user puts their API key in the `headers` field of their Claude MCP config. The server reads it from every incoming HTTP request via Starlette middleware and makes it available to tools via a Python `ContextVar`.

## Configuration After Change

### Server (admin sets once)

`docker-compose.yml` / `.env`:
```
SURE_API_URL=http://sure-instance:3000
SURE_TIMEOUT=30
SURE_VERIFY_SSL=false
# SURE_API_KEY removed — no longer server-side
```

### Each User's Claude Config

```json
{
  "mcpServers": {
    "Sure": {
      "url": "http://nas-ip:8765/sse",
      "headers": {
        "X-Sure-Api-Key": "their-personal-api-key"
      }
    }
  }
}
```

## Implementation Plan

### 1. `server.py`

- Add `from contextvars import ContextVar` import.
- Add `_api_key_var: ContextVar[Optional[str]] = ContextVar("api_key", default=None)`.
- Add Starlette middleware class `ApiKeyMiddleware`:
  - Reads `X-Sure-Api-Key` from request headers.
  - Sets `_api_key_var` for the request context.
  - Returns HTTP 403 with a descriptive JSON error if the header is missing (SSE mode only — skip check if running stdio).
- Mount middleware onto FastMCP's underlying Starlette app after `mcp = FastMCP(...)`.
- Update `get_auth_header()`:
  - Check `_api_key_var.get()` first.
  - Fall back to `os.getenv("SURE_API_KEY")` (preserves local/stdio backward compat).
  - Fall back to `os.getenv("SURE_ACCESS_TOKEN")`.
  - Raise `RuntimeError` if none found.

### 2. `docker-compose.yml`

- Remove `SURE_API_KEY` environment line.

### 3. `.env.example`

- Remove `SURE_API_KEY` and `SURE_ACCESS_TOKEN` lines (or comment with explanation).
- Add comment explaining keys now come from Claude client headers.

### 4. `setup_authentication` tool text

- Update instructions to show `headers` config instead of `env`.

### 5. `README.md`

- Update SSE/Docker deployment section to show `headers` config.
- Keep local Docker `env` config for backward compat (stdio mode still uses env).

## Backward Compatibility

| Mode | API key source | Change needed? |
|---|---|---|
| Local Docker (stdio) | `env` in Claude config | None |
| Manual install (stdio) | `env` in Claude config | None |
| SSE/NAS (HTTP) | `headers` in Claude config | Yes — switch `env` → `headers` |

## Security Notes

- HTTP headers are not logged by default in most proxies/servers.
- Keys are never stored on the server; they live only in the request context for the duration of that request.
- If the header is absent, the server returns 403 before any tool logic runs.
