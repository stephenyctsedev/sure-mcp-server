# Project Navigation Map

**System Overview**
- Python 3.12 MCP server that exposes Sure personal-finance API tools over SSE/stdio using FastMCP, Starlette/uvicorn, httpx, and a small SQLite-backed OAuth store.

**Project Tree**
```text
.
├─ src/
│  └─ sure_mcp_server/
│     ├─ server.py
│     ├─ oauth_routes.py
│     └─ auth_db.py
├─ tests/
├─ docs/
│  └─ superpowers/
│     └─ specs/
├─ docker-compose.yml
├─ Dockerfile
├─ pyproject.toml
└─ README.md
```

**Core Entry Points**
- src/sure_mcp_server/server.py
- pyproject.toml (console script `sure-mcp-server` -> `sure_mcp_server.server:main`)

**Module Map**
| Path | Responsibility |
| --- | --- |
| src/sure_mcp_server/server.py | FastMCP app, tool handlers, auth middleware, HTTP client, SSE app wiring, `main()` |
| src/sure_mcp_server/oauth_routes.py | OAuth 2.0 auth-code endpoints and HTML login form |
| src/sure_mcp_server/auth_db.py | SQLite store for auth codes and bearer tokens |
| tests/ | Pytest coverage for auth and tool behaviors |
| docs/superpowers/specs/ | Design specs for category-related tools |
| docker-compose.yml | Container runtime configuration |
| Dockerfile | Container image build |
| pyproject.toml | Build metadata, dependencies, entrypoint |

**Key Data Models/Interfaces**
- AuthDB records: `auth_codes(code, api_key, state, expires_at)`, `tokens(token, api_key, created_at)`
- Transaction payload: `account_id`, `amount`, `name`, `date`, optional `category_id`, `notes`, `nature`
- Category payload: `name`, `classification`, optional `color`, `icon`, `parent_id`
- Chat payload: `title`; message payload: `content`

**Critical Data Flows**
- OAuth Flow: `oauth_routes` -> `AuthDB` (auth code) -> token exchange -> `AuthMiddleware` -> request ContextVar
- Request Auth Flow: `AuthMiddleware` -> ContextVar -> `get_auth_header()` -> httpx client
- Tool Call Flow: MCP tool -> httpx -> Sure API `/api/v1/*` -> `handle_response()` -> JSON string

**Development Patterns**
- FastMCP tool registry via `@mcp.tool()`
- Pure ASGI middleware for SSE compatibility
- Lightweight SQLite token store
- Environment-driven configuration
