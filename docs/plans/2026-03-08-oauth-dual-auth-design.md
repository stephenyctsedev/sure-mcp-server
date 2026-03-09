# OAuth + Header Dual Auth Design

**Date:** 2026-03-08
**Branch:** `feature/per-user-api-key`
**Status:** Approved — supersedes `2026-03-08-per-user-api-key-design.md`

## Problem

Claude.ai (web) uses OAuth 2.0 Authorization Code + PKCE for remote MCP connectors — it hits `/authorize` on the MCP server, which currently returns 404. Claude Desktop supports raw HTTP headers. Both client types need to authenticate with their own personal Sure API key against a shared server.

## Decision

Add a lightweight OAuth 2.0 server directly to FastMCP's Starlette app (Option A). All auth paths converge on a single `ContextVar` so tool code is unchanged.

## Architecture

```
Claude.ai web          Claude Desktop         Local/stdio
     │                      │                     │
OAuth Bearer token     X-Sure-Api-Key header   SURE_API_KEY env
     │                      │                     │
     └──────────────┬────────────────────────────┘
                    │
             AuthMiddleware
              (per request)
                    │
             _api_key_var (ContextVar)
                    │
             Tool functions (unchanged)
```

## New Components

### 1. `AuthDB` — SQLite wrapper

File: `src/sure_mcp_server/auth_db.py`

Two tables in `/app/data/auth.db`:

```sql
CREATE TABLE auth_codes (
    code       TEXT PRIMARY KEY,
    api_key    TEXT NOT NULL,
    state      TEXT NOT NULL,
    expires_at INTEGER NOT NULL   -- unix timestamp, 10 min TTL
);

CREATE TABLE tokens (
    token      TEXT PRIMARY KEY,
    api_key    TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
```

- Codes and tokens are `secrets.token_hex(32)`
- Expired codes cleaned up on each `/token` request
- Database file persisted via Docker named volume

### 2. OAuth Routes — 3 Starlette routes

Mounted on FastMCP's Starlette app.

#### `GET /.well-known/oauth-authorization-server`
Returns JSON discovery document pointing to `/authorize` and `/token`.

#### `GET /authorize`
Returns a minimal HTML form:
- Heading: "Connect Sure Finance"
- Text input: "Your Sure API Key"
- Hidden inputs: `redirect_uri`, `state`, `code_challenge`, `code_challenge_method`, `client_id`
- Submit button: "Connect"

#### `POST /authorize` (form submission)
- Validates all required OAuth params are present
- Generates auth code, stores `(code → api_key, state, expires_at)` in SQLite
- Redirects to `redirect_uri?code=<code>&state=<state>`

#### `POST /token`
- Validates `grant_type=authorization_code` and `code`
- Looks up code in SQLite, checks not expired
- Deletes the code (single use)
- Issues `access_token`, stores `(token → api_key)` in SQLite
- Returns `{"access_token": "...", "token_type": "bearer"}`

### 3. `AuthMiddleware` — replaces old `ApiKeyMiddleware`

Priority order per request:

1. **OAuth endpoint?** (`/authorize`, `/token`, `/.well-known/...`) → pass through
2. **`Authorization: Bearer <token>`** → look up in SQLite → set `_api_key_var`
3. **`X-Sure-Api-Key: <key>`** → use directly → set `_api_key_var`
4. **`SURE_API_KEY` env var** → use → set `_api_key_var` (local/stdio fallback)
5. **None** → return 403 with message explaining both auth methods

## OAuth Flow

```
Claude.ai                    MCP Server
    │  GET /.well-known/...  │
    │──────────────────────► │  Returns authorize/token URLs
    │                        │
    │  GET /authorize?...    │
    │──────────────────────► │  Returns HTML form
    │                        │
    │  User enters API key   │
    │  POST /authorize       │
    │──────────────────────► │  Saves code→api_key in SQLite
    │◄────────────────────── │  Redirects to claude.ai + ?code&state
    │                        │
    │  POST /token {code}    │
    │──────────────────────► │  Exchanges code → token
    │◄────────────────────── │  {access_token, token_type: bearer}
    │                        │
    │  MCP requests          │
    │  Authorization: Bearer │
    │──────────────────────► │  Middleware: token→api_key via SQLite
```

## Configuration

### `.env` (server-side)
```
SURE_API_URL=http://localhost:9000
SURE_VERIFY_SSL=false
MCP_BASE_URL=https://your-public-url.example.com   # used in OAuth discovery + redirects
```

### `docker-compose.yml` additions
```yaml
volumes:
  - sure-mcp-data:/app/data
environment:
  - MCP_BASE_URL=${MCP_BASE_URL}

volumes:
  sure-mcp-data:
```

### Claude Desktop config (unchanged from header design)
```json
{
  "mcpServers": {
    "Sure": {
      "url": "https://your-public-url.example.com/sse",
      "headers": { "X-Sure-Api-Key": "personal-api-key" }
    }
  }
}
```

### Claude.ai web config
Add custom connector with URL: `https://your-public-url.example.com/sse`
No headers needed — OAuth handles auth.

## Security Notes

- Auth codes are single-use and expire in 10 minutes
- Tokens never expire (user removes and re-adds connector to rotate)
- No Sure API key is ever stored on the server in env — only in SQLite mapped to tokens
- PKCE `code_challenge` is stored but not verified (Claude.ai handles PKCE client-side; server is the auth server, not a client)
- SQLite file is inside a Docker volume, not in the repo

## Files Changed

| File | Change |
|------|--------|
| `src/sure_mcp_server/auth_db.py` | New — SQLite wrapper |
| `src/sure_mcp_server/oauth_routes.py` | New — OAuth endpoints |
| `src/sure_mcp_server/server.py` | Update middleware, mount OAuth routes, add `MCP_BASE_URL` |
| `docker-compose.yml` | Add volume, `MCP_BASE_URL` env |
| `.env.example` | Add `MCP_BASE_URL` |
| `README.md` | Update setup instructions |
