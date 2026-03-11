"""Sure MCP Server - Main server implementation."""

import os
import logging
import json
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse as StarletteJSONResponse
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("Sure MCP Server")

# Per-request API key (set by AuthMiddleware from OAuth Bearer token or X-Sure-Api-Key header)
_api_key_var: ContextVar[str | None] = ContextVar("api_key", default=None)


class AuthMiddleware:
    """Pure ASGI middleware: authenticate via Bearer token (OAuth), X-Sure-Api-Key header, or env var.

    Uses pure ASGI (not BaseHTTPMiddleware) to avoid the streaming/SSE incompatibility in Starlette.
    """

    _OPEN_PREFIXES = ("/.well-known/",)
    _OPEN_PATHS = frozenset(["/authorize", "/token", "/register"])

    def __init__(self, app, auth_db, base_url: str = "") -> None:
        self.app = app
        self.auth_db = auth_db
        self.base_url = base_url

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path in self._OPEN_PATHS or any(path.startswith(p) for p in self._OPEN_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        api_key: str | None = None

        # 1. OAuth Bearer token
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.startswith("Bearer "):
            api_key = self.auth_db.get_api_key_for_token(auth_header[7:])

        # 2. X-Sure-Api-Key header (Claude Desktop)
        if not api_key:
            raw = headers.get(b"x-sure-api-key", b"")
            api_key = raw.decode() if raw else None

        # 3. Env var fallback (local/stdio mode)
        if not api_key:
            api_key = os.getenv("SURE_API_KEY")

        if not api_key:
            resource_metadata_url = f"{self.base_url}/.well-known/oauth-protected-resource"
            response = StarletteJSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"'
                },
            )
            await response(scope, receive, send)
            return

        token = _api_key_var.set(api_key)
        try:
            await self.app(scope, receive, send)
        finally:
            _api_key_var.reset(token)


def get_api_url() -> str:
    """Get the Sure API base URL."""
    url = os.getenv("SURE_API_URL")
    if not url:
        raise RuntimeError("❌ SURE_API_URL not configured. Set it in your environment.")
    return url.rstrip("/")


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


def get_client() -> httpx.Client:
    """Get configured HTTP client for Sure API."""
    timeout = int(os.getenv("SURE_TIMEOUT", "30"))
    verify_ssl = os.getenv("SURE_VERIFY_SSL", "true").lower() == "true"

    return httpx.Client(
        base_url=get_api_url(),
        timeout=timeout,
        verify=verify_ssl,
        headers=get_auth_header()
    )


def handle_response(response: httpx.Response) -> Any:
    """Handle API response and raise appropriate errors."""
    if response.status_code == 401:
        raise RuntimeError("❌ Authentication failed. Check your API key.")
    elif response.status_code == 403:
        raise RuntimeError("❌ Permission denied. Check API key scopes.")
    elif response.status_code == 404:
        raise RuntimeError("❌ Resource not found.")
    elif response.status_code == 429:
        raise RuntimeError("❌ Rate limited. Please wait and try again.")
    elif response.status_code >= 400:
        raise RuntimeError(f"❌ API error {response.status_code}: {response.text}")

    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


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


@mcp.tool()
def check_auth_status() -> str:
    """Check if authentication is configured for Sure API."""
    try:
        api_url = os.getenv("SURE_API_URL")
        api_key = os.getenv("SURE_API_KEY")
        access_token = os.getenv("SURE_ACCESS_TOKEN")

        status = ""

        if api_url:
            status += f"✅ API URL: {api_url}\n"
        else:
            status += "❌ SURE_API_URL not configured\n"

        if api_key:
            status += "✅ API Key configured\n"
        elif access_token:
            status += "✅ Access Token configured\n"
        else:
            status += "❌ No authentication configured (SURE_API_KEY or SURE_ACCESS_TOKEN)\n"

        status += "\n💡 Try get_accounts to test the connection."

        return status
    except Exception as e:
        return f"Error checking auth status: {str(e)}"


@mcp.tool()
def check_connection() -> str:
    """Test connection to Sure API."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/usage")
            data = handle_response(response)

            return f"✅ Connected to Sure API\n{json.dumps(data, indent=2, default=str)}"
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return f"❌ Connection failed: {str(e)}"


@mcp.tool()
def get_accounts() -> str:
    """Get all financial accounts from Sure."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/accounts")
            data = handle_response(response)

            # Handle paginated response
            accounts = data.get("accounts") or data.get("data") or data
            if isinstance(accounts, dict):
                accounts = accounts.get("accounts", [])

            logger.info(f"✅ Retrieved {len(accounts) if isinstance(accounts, list) else 'unknown'} accounts")
            return json.dumps(accounts, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get accounts: {e}")
        return f"Error getting accounts: {str(e)}"


@mcp.tool()
def get_transactions(
    limit: int = 25,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_ids: Optional[str] = None,
    category_ids: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """
    Get transactions from Sure.

    Args:
        limit: Number of transactions per page (default: 25, max: 100)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        account_ids: Comma-separated account IDs to filter by
        category_ids: Comma-separated category IDs to filter by
        search: Search term to filter transactions
    """
    try:
        with get_client() as client:
            params: Dict[str, Any] = {"per_page": min(limit, 100)}

            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            if account_ids:
                params["account_ids"] = account_ids
            if category_ids:
                params["category_ids"] = category_ids
            if search:
                params["search"] = search

            response = client.get("/api/v1/transactions", params=params)
            data = handle_response(response)

            # Handle paginated response
            transactions = data.get("transactions") or data.get("data") or data
            if isinstance(transactions, dict):
                transactions = transactions.get("transactions", [])

            logger.info(f"✅ Retrieved {len(transactions) if isinstance(transactions, list) else 'unknown'} transactions")
            return json.dumps(transactions, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        return f"Error getting transactions: {str(e)}"


@mcp.tool()
def get_transaction(transaction_id: str) -> str:
    """
    Get a single transaction by ID.

    Args:
        transaction_id: The ID of the transaction
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/transactions/{transaction_id}")
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get transaction: {e}")
        return f"Error getting transaction: {str(e)}"


@mcp.tool()
def create_transaction(
    account_id: str,
    amount: float,
    name: str,
    date: str,
    category_id: Optional[str] = None,
    notes: Optional[str] = None,
    nature: Optional[str] = None,
) -> str:
    """
    Create a new transaction in Sure.

    Args:
        account_id: The account ID to add the transaction to
        amount: Transaction amount (use nature to specify income/expense)
        name: Transaction name/payee
        date: Transaction date in YYYY-MM-DD format
        category_id: Optional category ID
        notes: Optional notes
        nature: Optional "income" or "expense" to set amount sign
    """
    try:
        with get_client() as client:
            payload: Dict[str, Any] = {
                "account_id": account_id,
                "amount": amount,
                "name": name,
                "date": date,
            }

            if category_id:
                payload["category_id"] = category_id
            if notes:
                payload["notes"] = notes
            if nature:
                payload["nature"] = nature

            response = client.post(
                "/api/v1/transactions",
                json={"transaction": payload}
            )
            data = handle_response(response)

            logger.info(f"✅ Created transaction")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return f"Error creating transaction: {str(e)}"


@mcp.tool()
def update_transaction(
    transaction_id: str,
    amount: Optional[float] = None,
    name: Optional[str] = None,
    date: Optional[str] = None,
    category_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Update an existing transaction in Sure.

    Args:
        transaction_id: The ID of the transaction to update
        amount: New transaction amount
        name: New transaction name/payee
        date: New transaction date in YYYY-MM-DD format
        category_id: New category ID
        notes: New notes
    """
    try:
        with get_client() as client:
            payload: Dict[str, Any] = {}

            if amount is not None:
                payload["amount"] = amount
            if name is not None:
                payload["name"] = name
            if date is not None:
                payload["date"] = date
            if category_id is not None:
                payload["category_id"] = category_id
            if notes is not None:
                payload["notes"] = notes

            response = client.patch(
                f"/api/v1/transactions/{transaction_id}",
                json={"transaction": payload}
            )
            data = handle_response(response)

            logger.info(f"✅ Updated transaction {transaction_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update transaction: {e}")
        return f"Error updating transaction: {str(e)}"


@mcp.tool()
def delete_transaction(transaction_id: str) -> str:
    """
    Delete a transaction from Sure.

    Args:
        transaction_id: The ID of the transaction to delete
    """
    try:
        with get_client() as client:
            response = client.delete(f"/api/v1/transactions/{transaction_id}")
            data = handle_response(response)

            logger.info(f"✅ Deleted transaction {transaction_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return f"Error deleting transaction: {str(e)}"


@mcp.tool()
def link_transfer(transaction_id: str, other_transaction_id: str) -> str:
    """
    Link two transactions as a transfer between accounts in Sure.

    This marks one transaction as the inflow and the other as the outflow of a
    single transfer event. The API automatically assigns direction.

    Args:
        transaction_id: The ID of the first transaction
        other_transaction_id: The ID of the second transaction to link as a transfer pair

    Business rules:
        - Both transactions must belong to different accounts within the same family
        - They must have opposite-sign amounts (one positive, one negative)
        - They must be dated within 30 days of each other
        - Each transaction can only be linked to one transfer at a time
    """
    try:
        with get_client() as client:
            response = client.patch(
                f"/api/v1/transactions/{transaction_id}/transfer",
                json={"transfer": {"other_transaction_id": other_transaction_id}}
            )
            data = handle_response(response)

            logger.info(f"✅ Linked transfer between {transaction_id} and {other_transaction_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to link transfer: {e}")
        return f"Error linking transfer: {str(e)}"


@mcp.tool()
def get_categories() -> str:
    """Get all transaction categories from Sure."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/categories")
            data = handle_response(response)

            # Handle paginated response
            categories = data.get("categories") or data.get("data") or data
            if isinstance(categories, dict):
                categories = categories.get("categories", [])

            logger.info(f"✅ Retrieved {len(categories) if isinstance(categories, list) else 'unknown'} categories")
            return json.dumps(categories, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get categories: {e}")
        return f"Error getting categories: {str(e)}"


@mcp.tool()
def get_category(category_id: str) -> str:
    """
    Get a single category by ID.

    Args:
        category_id: The ID of the category
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/categories/{category_id}")
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get category: {e}")
        return f"Error getting category: {str(e)}"


@mcp.tool()
def create_category(
    name: str,
    classification: str,
    color: Optional[str] = None,
    icon: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> str:
    """
    Create a new category in Sure.

    Args:
        name: Category name
        classification: "income" or "expense"
        color: Optional color string (e.g. hex code like "#ff0000")
        icon: Optional icon identifier
        parent_id: Optional parent category ID for nesting
    """
    try:
        if classification not in ("income", "expense"):
            return "Error creating category: classification must be 'income' or 'expense'"

        with get_client() as client:
            payload: Dict[str, Any] = {
                "name": name,
                "classification": classification,
            }

            if color is not None:
                payload["color"] = color
            if icon is not None:
                payload["icon"] = icon
            if parent_id is not None:
                payload["parent_id"] = parent_id

            response = client.post(
                "/api/v1/categories",
                json={"category": payload}
            )
            data = handle_response(response)

            logger.info(f"✅ Created category '{name}'")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create category: {e}")
        return f"Error creating category: {str(e)}"


@mcp.tool()
def sync_accounts() -> str:
    """Trigger account sync to refresh data from financial institutions."""
    try:
        with get_client() as client:
            response = client.post("/api/v1/sync")
            data = handle_response(response)

            logger.info("✅ Triggered account sync")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to sync accounts: {e}")
        return f"Error syncing accounts: {str(e)}"


@mcp.tool()
def get_usage() -> str:
    """Get API usage and rate limit information."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/usage")
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get usage: {e}")
        return f"Error getting usage: {str(e)}"


@mcp.tool()
def list_chats() -> str:
    """Get all AI chat sessions from Sure."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/chats")
            data = handle_response(response)

            # Handle paginated response
            chats = data.get("chats") or data.get("data") or data
            if isinstance(chats, dict):
                chats = chats.get("chats", [])

            logger.info(f"✅ Retrieved {len(chats) if isinstance(chats, list) else 'unknown'} chats")
            return json.dumps(chats, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to list chats: {e}")
        return f"Error listing chats: {str(e)}"


@mcp.tool()
def create_chat(title: Optional[str] = None) -> str:
    """
    Create a new AI chat session in Sure.

    Args:
        title: Optional title for the chat
    """
    try:
        with get_client() as client:
            payload: Dict[str, Any] = {}
            if title:
                payload["title"] = title

            response = client.post("/api/v1/chats", json=payload)
            data = handle_response(response)

            logger.info("✅ Created new chat")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to create chat: {e}")
        return f"Error creating chat: {str(e)}"


@mcp.tool()
def get_chat(chat_id: str) -> str:
    """
    Get a chat session by ID.

    Args:
        chat_id: The ID of the chat
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/chats/{chat_id}")
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get chat: {e}")
        return f"Error getting chat: {str(e)}"


@mcp.tool()
def send_message(chat_id: str, content: str) -> str:
    """
    Send a message to Sure's AI assistant.

    Args:
        chat_id: The ID of the chat
        content: The message content
    """
    try:
        with get_client() as client:
            response = client.post(
                f"/api/v1/chats/{chat_id}/messages",
                json={"content": content}
            )
            data = handle_response(response)

            logger.info("✅ Sent message")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return f"Error sending message: {str(e)}"


@mcp.tool()
def delete_chat(chat_id: str) -> str:
    """
    Delete a chat session.

    Args:
        chat_id: The ID of the chat to delete
    """
    try:
        with get_client() as client:
            response = client.delete(f"/api/v1/chats/{chat_id}")
            data = handle_response(response)

            logger.info(f"✅ Deleted chat {chat_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete chat: {e}")
        return f"Error deleting chat: {str(e)}"


def main():
    """Main entry point for the server."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from sure_mcp_server.auth_db import AuthDB
    from sure_mcp_server.oauth_routes import make_oauth_routes

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8765"))
    base_url = os.getenv("MCP_BASE_URL", f"http://localhost:{port}").rstrip("/")

    logger.info(f"Starting Sure MCP Server (SSE) on {host}:{port}...")
    logger.info(f"OAuth base URL: {base_url}")

    # Initialise SQLite auth store
    auth_db = AuthDB()
    auth_db.initialize()

    # Build combined app: OAuth routes + FastMCP SSE app under /
    oauth_routes = make_oauth_routes(auth_db, base_url)
    sse = mcp.sse_app()

    # MCP transport security validates the Host header against the bind address.
    # Behind a reverse proxy the Host header is the external domain, which fails.
    # Normalise it to localhost:port before the MCP SSE app sees it.
    internal_host = f"localhost:{port}".encode()

    class _HostNormalizerMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] in ("http", "websocket"):
                scope["headers"] = [
                    (b"host", internal_host) if k.lower() == b"host" else (k, v)
                    for k, v in scope["headers"]
                ]
            await self.app(scope, receive, send)

    inner = Starlette(routes=oauth_routes + [Mount("/", app=_HostNormalizerMiddleware(sse))])
    # Wrap with pure ASGI middleware — BaseHTTPMiddleware breaks SSE streaming
    app_with_auth = AuthMiddleware(inner, auth_db=auth_db, base_url=base_url)

    uvicorn.run(app_with_auth, host=host, port=port)


# Export for mcp run
app = mcp

if __name__ == "__main__":
    main()
