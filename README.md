# Sure MCP Server

A Model Context Protocol (MCP) server for integrating with the [Sure](https://github.com/we-promise/sure) self-hosted personal finance platform. Supports Claude.ai web (via OAuth) and Claude Desktop (via API key header).

## Quick Start

There are three ways to run the Sure MCP Server depending on your setup.

---

### Option A: Shared SSE Server — Claude.ai Web (OAuth)

Run the server once on a NAS or home server. Claude.ai web users authenticate with their own Sure API key via OAuth — no key is stored on the server.

1. **On the server**, create a `.env` file:
   ```
   SURE_API_URL=http://your-sure-instance:3000
   SURE_VERIFY_SSL=false
   MCP_BASE_URL=https://your-public-domain.example.com
   ```

2. **Start the server**:
   ```bash
   docker compose up -d
   ```

3. **In Claude.ai**, go to **Settings → Connectors → Add custom connector**:
   - **Name**: Sure Finance
   - **URL**: `https://your-public-domain.example.com/sse`
   - Click **Add** — you'll be redirected to a login page

4. **Enter your Sure API key** in the browser form (from Sure's **Settings > API Key** page)

5. Done — each user connects with their own key via OAuth

---

### Option B: Shared SSE Server — Claude Desktop (API Key Header)

Run the server on a NAS or home server. Each Claude Desktop user passes their own API key per request.

1. **On the server**, create a `.env` file:
   ```
   SURE_API_URL=http://your-sure-instance:3000
   SURE_VERIFY_SSL=false
   MCP_BASE_URL=http://your-nas-ip:8765
   ```

2. **Start the server**:
   ```bash
   docker compose up -d
   ```

3. **Each user** adds this to their Claude Desktop config:

   **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

   **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

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

   > Each user uses their own API key from Sure's **Settings > API Key** page. Keys are sent per-request and never stored on the server.

4. **Restart Claude Desktop**

---

### Option C: Local Docker (single user)

Run the server locally via Docker stdio mode. Your API key stays in your Claude config.

1. **Build the Docker image**:
   ```bash
   docker compose build
   ```

2. **Configure Claude Desktop**:

   ```json
   {
     "mcpServers": {
       "Sure": {
         "command": "docker",
         "args": [
           "run", "-i", "--rm",
           "-e", "SURE_API_URL",
           "-e", "SURE_API_KEY",
           "-e", "SURE_VERIFY_SSL",
           "--add-host=host.docker.internal:host-gateway",
           "sure-mcp-server"
         ],
         "env": {
           "SURE_API_URL": "http://host.docker.internal:3000",
           "SURE_API_KEY": "your-api-key-here",
           "SURE_VERIFY_SSL": "false"
         }
       }
     }
   }
   ```

   **Note**: Use `host.docker.internal` to connect to Sure running on your host machine.

3. **Restart Claude Desktop**

---

### Get Your Sure API Key

1. Log into Sure at your Sure instance URL
2. Go to **Settings > API Key** and generate a new key
3. Copy it into your Claude config (`headers` for SSE mode, browser form for OAuth, `env` for local mode)

### Start Using in Claude Desktop

Once configured, use these tools directly in Claude Desktop:
- `list_accounts` - View all accounts
- `list_transactions` - Recent transactions
- `list_categories` - Transaction categories
- `sync_accounts` - Trigger account sync
- `link_transfer` - Link two transactions as a transfer
- `get_category_icons` - Browse available category icons

## Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `setup_authentication` | Get setup instructions | None |
| `check_auth_status` | Check authentication status | None |
| `check_connection` | Test API connection | None |
| `list_accounts` | List all financial accounts | `page`, `per_page` |
| `get_account` | Get single account | `account_id` |
| `create_account` | Create a new manual account | `name`, `accountable_type`, `balance`, `currency`, `institution_name`, `notes`, `opening_balance_date` |
| `update_account` | Update account name, balance, or notes | `account_id`, `name`, `balance`, `institution_name`, `notes` |
| `list_transactions` | List transactions with filtering | `limit`, `start_date`, `end_date`, `account_ids`, `category_ids`, `search` |
| `get_transaction` | Get single transaction | `transaction_id` |
| `create_transaction` | Create new transaction | `account_id`, `amount`, `name`, `date`, `category_id`, `notes`, `nature` |
| `update_transaction` | Update transaction | `transaction_id`, `amount`, `name`, `date`, `category_id`, `notes` |
| `delete_transaction` | Delete transaction | `transaction_id` |
| `link_transfer` | Link two transactions as a transfer | `transaction_id`, `other_transaction_id` |
| `list_categories` | List all categories | None |
| `get_category` | Get single category | `category_id` |
| `create_category` | Create new category | `name`, `classification`, `color`, `icon`, `parent_id` |
| `update_category` | Update existing category | `category_id`, `name`, `classification`, `color`, `icon`, `parent_id` |
| `delete_category` | Delete category | `category_id` |
| `get_category_icons` | Get available category icons | None |
| `sync_accounts` | Trigger account sync | None |
| `get_usage` | Get API usage info | None |
| `list_chats` | List AI chat sessions | None |
| `create_chat` | Create new chat | `title` |
| `get_chat` | Get chat details | `chat_id` |
| `send_message` | Send message to AI | `chat_id`, `content` |
| `delete_chat` | Delete chat session | `chat_id` |

## Configuration

| Variable | Required | Where | Description |
|----------|----------|-------|-------------|
| `SURE_API_URL` | Yes | Server `.env` | Base URL of your Sure instance |
| `MCP_BASE_URL` | Yes (SSE mode) | Server `.env` | Public URL of this server (used in OAuth discovery) |
| `SURE_API_KEY` | No | Client `env` (local only) | API key for local/stdio mode only |
| `SURE_TIMEOUT` | No | Server `.env` | Request timeout in seconds (default: 30) |
| `SURE_VERIFY_SSL` | No | Server `.env` | Verify SSL certificates (default: true) |

> In SSE/shared server mode, `SURE_API_KEY` is **not** stored on the server. Claude.ai web users authenticate via OAuth; Claude Desktop users pass their key via the `headers` field.

## Auth Flow

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
             Tool functions
```

## Date Formats

- All dates should be in `YYYY-MM-DD` format (e.g., "2024-12-15")
- Transaction amounts: use `nature` field to specify "income" or "expense"

## Troubleshooting

### Connection Issues
1. Verify Sure is running: `docker compose ps`
2. Check the API URL is correct
3. Try `check_connection` tool to diagnose

### Authentication Issues
1. **Claude.ai web**: Re-add the connector to go through OAuth again
2. **Claude Desktop**: Verify `headers` has `X-Sure-Api-Key` with your key
3. **Local mode**: Verify `SURE_API_KEY` is set in `env`
4. Check the key hasn't expired — regenerate in Sure settings

## Project Structure

```
sure-mcp-server/
├── src/sure_mcp_server/
│   ├── __init__.py
│   ├── server.py         # Main server, AuthMiddleware, tools
│   ├── auth_db.py        # SQLite token store
│   └── oauth_routes.py   # OAuth 2.0 endpoints
├── tests/
│   ├── test_auth_db.py
│   ├── test_middleware.py
│   ├── test_oauth_routes.py
│   ├── test_tools_account.py
│   └── test_tools_category.py
├── docs/
│   ├── plans/            # OAuth and auth design docs
│   └── superpowers/      # Category feature specs and plans
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
└── README.md
```

## License

MIT License
