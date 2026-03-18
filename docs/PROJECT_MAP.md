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
│  ├─ test_auth_db.py
│  ├─ test_middleware.py
│  ├─ test_oauth_routes.py
│  ├─ test_tools_account.py
│  └─ test_tools_category.py
├─ docs/
│  ├─ plans/
│  └─ superpowers/
│     ├─ plans/
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
| tests/test_auth_db.py | Unit tests for AuthDB token/code lifecycle |
| tests/test_middleware.py | Tests for AuthMiddleware auth resolution |
| tests/test_oauth_routes.py | Tests for OAuth 2.0 endpoints |
| tests/test_tools_account.py | Tests for account tool handlers |
| tests/test_tools_category.py | Tests for category tool handlers |
| docs/plans/ | OAuth and per-user API key design docs |
| docs/superpowers/specs/ | Design specs for category-related tools |
| docs/superpowers/plans/ | Implementation plans for category features |
| docker-compose.yml | Container runtime configuration |
| Dockerfile | Container image build |
| pyproject.toml | Build metadata, dependencies, entrypoint |

**Tool Inventory**
| Tool | API Endpoint | Notes |
| --- | --- | --- |
| `setup_authentication` | — | Returns setup instructions string |
| `check_auth_status` | — | Reports configured auth sources |
| `check_connection` | GET /api/v1/usage | Smoke-test connectivity |
| `list_accounts` | GET /api/v1/accounts | Optional `page`, `per_page` |
| `get_account` | GET /api/v1/accounts/:id | Single account |
| `create_account` | POST /api/v1/accounts | `name`, `accountable_type` required |
| `update_account` | PATCH /api/v1/accounts/:id | Partial update |
| `list_transactions` | GET /api/v1/transactions | Filtering + pagination |
| `get_transaction` | GET /api/v1/transactions/:id | Single transaction |
| `create_transaction` | POST /api/v1/transactions | |
| `update_transaction` | PATCH /api/v1/transactions/:id | Partial update |
| `delete_transaction` | DELETE /api/v1/transactions/:id | |
| `link_transfer` | PATCH /api/v1/transactions/:id/transfer | Links transfer pair |
| `list_categories` | GET /api/v1/categories | |
| `get_category` | GET /api/v1/categories/:id | Single category |
| `create_category` | POST /api/v1/categories | `name`, `classification` required |
| `update_category` | PATCH /api/v1/categories/:id | `parent_id="empty"` to unlink |
| `delete_category` | DELETE /api/v1/categories/:id | |
| `get_category_icons` | GET /api/v1/categories/icons | |
| `sync_accounts` | POST /api/v1/sync | |
| `get_usage` | GET /api/v1/usage | Rate limit info |
| `list_chats` | GET /api/v1/chats | |
| `create_chat` | POST /api/v1/chats | Optional `title` |
| `get_chat` | GET /api/v1/chats/:id | |
| `send_message` | POST /api/v1/chats/:id/messages | |
| `delete_chat` | DELETE /api/v1/chats/:id | |

**Key Data Models/Interfaces**
- AuthDB records: `auth_codes(code, api_key, state, expires_at)`, `tokens(token, api_key, created_at)`
- Account payload: `name`, `accountable_type` (PascalCase: Depository/Investment/Crypto/Property/Vehicle/OtherAsset/CreditCard/Loan/OtherLiability), optional `balance`, `currency`, `institution_name`, `notes`, `opening_balance_date`
- Transaction payload: `account_id`, `amount`, `name`, `date`, optional `category_id`, `notes`, `nature`
- Category payload: `name`, `classification` ("income"/"expense"), optional `color`, `icon`, `parent_id`
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
- Rate limit warnings surfaced via `check_rate_limit()` appended to tool output
