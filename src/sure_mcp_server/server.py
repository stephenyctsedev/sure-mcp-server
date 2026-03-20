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
mcp = FastMCP("Sure app")

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
    if response.status_code >= 400:
        try:
            error_data = response.json()
            error_msg = error_data.get("message") or error_data.get("error") or response.text
        except Exception:
            error_msg = response.text

        if response.status_code == 401:
            raise RuntimeError(f"❌ HTTP 401: Authentication failed. Check your API key. {error_msg}")
        elif response.status_code == 403:
            raise RuntimeError(f"❌ HTTP 403: Permission denied. Check API key scopes. {error_msg}")
        elif response.status_code == 404:
            raise RuntimeError(f"❌ HTTP 404: Resource not found. {error_msg}")
        elif response.status_code == 422:
            raise RuntimeError(f"❌ HTTP 422: Validation failed. {error_msg}")
        elif response.status_code == 429:
            raise RuntimeError(f"❌ HTTP 429: Rate limited. Please wait and try again. {error_msg}")
        else:
            raise RuntimeError(f"❌ HTTP {response.status_code}: {error_msg}")

    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


def check_rate_limit(response: httpx.Response) -> str:
    """Return a warning string if X-RateLimit-Remaining is low (< 10), else empty string."""
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            if int(remaining) < 10:
                return f"\n\n⚠️ Rate limit warning: only {remaining} API requests remaining. Please reduce request frequency."
        except ValueError:
            pass
    return ""


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
        oauth_key = _api_key_var.get()
        api_key = os.getenv("SURE_API_KEY")
        access_token = os.getenv("SURE_ACCESS_TOKEN")

        status = ""

        if api_url:
            status += f"✅ API URL: {api_url}\n"
        else:
            status += "❌ SURE_API_URL not configured\n"

        if oauth_key:
            status += "✅ API Key configured (OAuth session)\n"
        elif api_key:
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
def list_accounts(
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> str:
    """
    List all financial accounts from Sure with optional pagination.

    Args:
        page: Page number (1-based)
        per_page: Number of accounts per page
    """
    try:
        with get_client() as client:
            params: Dict[str, Any] = {}
            if page is not None:
                params["page"] = page
            if per_page is not None:
                params["per_page"] = per_page

            response = client.get("/api/v1/accounts", params=params)
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            # Handle paginated response
            accounts = data.get("accounts") or data.get("data") or data
            if isinstance(accounts, dict):
                accounts = accounts.get("accounts", [])

            logger.info(f"✅ Retrieved {len(accounts) if isinstance(accounts, list) else 'unknown'} accounts")
            return json.dumps(accounts, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to list accounts: {e}")
        return f"Error listing accounts: {str(e)}"


@mcp.tool()
def get_account(account_id: str) -> str:
    """
    Retrieve a single account by ID.

    Args:
        account_id: The ID of the account
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/accounts/{account_id}")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to get account: {e}")
        return f"Error getting account: {str(e)}"


_ACCOUNTABLE_TYPES = (
    "Depository", "Investment", "Crypto", "Property",
    "Vehicle", "OtherAsset", "CreditCard", "Loan", "OtherLiability",
)


@mcp.tool()
def create_account(
    name: str,
    accountable_type: str,
    balance: Optional[float] = None,
    currency: Optional[str] = None,
    institution_name: Optional[str] = None,
    notes: Optional[str] = None,
    opening_balance_date: Optional[str] = None,
) -> str:
    """
    Create a new manual account in Sure.

    Args:
        name: Account name, e.g. 'My Savings'
        accountable_type: Account type (PascalCase). Must be one of: Depository
            (checking/savings), Investment (brokerage/retirement), Crypto (crypto
            wallet), Property (real estate), Vehicle (car/boat), OtherAsset (any
            other asset), CreditCard (credit card), Loan (mortgage/personal loan),
            OtherLiability (any other liability).
        balance: Opening balance (default: 0)
        currency: ISO 4217 currency code, e.g. 'USD', 'CAD'
        institution_name: Bank or institution name
        notes: Free-text notes
        opening_balance_date: ISO 8601 date for the opening balance entry, e.g.
            '2024-01-01'. Defaults to 2 years ago.
    """
    try:
        if accountable_type not in _ACCOUNTABLE_TYPES:
            return (
                f"Error creating account: accountable_type must be one of "
                f"{_ACCOUNTABLE_TYPES}. Got '{accountable_type}'. "
                "Note: values are PascalCase (e.g. 'Depository', not 'depository')."
            )

        with get_client() as client:
            payload: Dict[str, Any] = {
                "name": name,
                "accountable_type": accountable_type,
            }

            if balance is not None:
                payload["balance"] = balance
            if currency is not None:
                payload["currency"] = currency
            if institution_name is not None:
                payload["institution_name"] = institution_name
            if notes is not None:
                payload["notes"] = notes
            if opening_balance_date is not None:
                payload["opening_balance_date"] = opening_balance_date

            response = client.post(
                "/api/v1/accounts",
                json={"account": payload}
            )
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Created account '{name}'")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to create account: {e}")
        return f"Error creating account: {str(e)}"


@mcp.tool()
def update_account(
    account_id: str,
    name: Optional[str] = None,
    balance: Optional[float] = None,
    institution_name: Optional[str] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Update an existing account's name, balance, institution name, or notes.
    Only include fields you want to change — omitted fields are left as-is.

    Note: accountable_type cannot be changed after creation — omit it.
    Changing balance creates a balance-adjustment entry to reconcile the difference;
    only send balance if you intend to update it.

    Args:
        account_id: Account UUID
        name: New account name
        balance: New current balance (creates a balance adjustment entry)
        institution_name: Bank or institution name
        notes: Free-text notes
    """
    try:
        with get_client() as client:
            payload: Dict[str, Any] = {}

            if name is not None:
                payload["name"] = name
            if balance is not None:
                payload["balance"] = balance
            if institution_name is not None:
                payload["institution_name"] = institution_name
            if notes is not None:
                payload["notes"] = notes

            response = client.patch(
                f"/api/v1/accounts/{account_id}",
                json={"account": payload}
            )
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Updated account {account_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to update account: {e}")
        return f"Error updating account: {str(e)}"


@mcp.tool()
def list_transactions(
    limit: int = 25,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    account_ids: Optional[str] = None,
    category_ids: Optional[str] = None,
    search: Optional[str] = None,
) -> str:
    """
    List transactions from Sure with filtering and pagination.

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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            # Handle paginated response
            transactions = data.get("transactions") or data.get("data") or data
            if isinstance(transactions, dict):
                transactions = transactions.get("transactions", [])

            logger.info(f"✅ Retrieved {len(transactions) if isinstance(transactions, list) else 'unknown'} transactions")
            return json.dumps(transactions, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to list transactions: {e}")
        return f"Error listing transactions: {str(e)}"


@mcp.tool()
def get_transaction(transaction_id: str) -> str:
    """
    Retrieve a single transaction by ID.

    Args:
        transaction_id: The ID of the transaction
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/transactions/{transaction_id}")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str) + rate_limit_note
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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Created transaction")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Updated transaction {transaction_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Deleted transaction {transaction_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Linked transfer between {transaction_id} and {other_transaction_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to link transfer: {e}")
        return f"Error linking transfer: {str(e)}"


@mcp.tool()
def list_categories() -> str:
    """List all spending categories from Sure."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/categories")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            # Handle paginated response
            categories = data.get("categories") or data.get("data") or data
            if isinstance(categories, dict):
                categories = categories.get("categories", [])

            logger.info(f"✅ Retrieved {len(categories) if isinstance(categories, list) else 'unknown'} categories")
            return json.dumps(categories, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to list categories: {e}")
        return f"Error listing categories: {str(e)}"


@mcp.tool()
def get_category(category_id: str) -> str:
    """
    Retrieve a single category by ID.

    Args:
        category_id: The ID of the category
    """
    try:
        with get_client() as client:
            response = client.get(f"/api/v1/categories/{category_id}")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            return json.dumps(data, indent=2, default=str) + rate_limit_note
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
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Created category '{name}'")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to create category: {e}")
        return f"Error creating category: {str(e)}"


@mcp.tool()
def update_category(
    category_id: str,
    name: Optional[str] = None,
    classification: Optional[str] = None,
    color: Optional[str] = None,
    icon: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> str:
    """
    Update an existing category in Sure.

    Args:
        category_id: The ID of the category to update
        name: New category name
        classification: New classification ("income" or "expense")
        color: New color string (e.g. hex code like "#ff0000")
        icon: New icon identifier
        parent_id: New parent category ID for nesting. Pass the special value
            "empty" to unlink the category from its current parent.
    """
    try:
        if classification is not None and classification not in ("income", "expense"):
            return "Error updating category: classification must be 'income' or 'expense'"

        with get_client() as client:
            payload: Dict[str, Any] = {}

            if name is not None:
                payload["name"] = name
            if classification is not None:
                payload["classification"] = classification
            if color is not None:
                payload["color"] = color
            if icon is not None:
                payload["icon"] = icon
            if parent_id is not None:
                payload["parent_id"] = None if parent_id == "empty" else parent_id

            response = client.patch(
                f"/api/v1/categories/{category_id}",
                json={"category": payload}
            )
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Updated category {category_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to update category: {e}")
        return f"Error updating category: {str(e)}"


@mcp.tool()
def delete_category(category_id: str) -> str:
    """
    Delete a category from Sure.

    Args:
        category_id: The ID of the category to delete
    """
    try:
        with get_client() as client:
            response = client.delete(f"/api/v1/categories/{category_id}")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            logger.info(f"✅ Deleted category {category_id}")
            return json.dumps(data, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to delete category: {e}")
        return f"Error deleting category: {str(e)}"


@mcp.tool()
def get_category_icons() -> str:
    """Get all available icon identifiers that can be used when creating or updating a category."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/categories/icons")
            rate_limit_note = check_rate_limit(response)
            data = handle_response(response)

            if isinstance(data, list):
                icons = data
            else:
                icons = data.get("icons") or data.get("data") or data
                if isinstance(icons, dict):
                    icons = icons.get("icons", [])

            logger.info(f"✅ Retrieved {len(icons) if isinstance(icons, list) else 'unknown'} icons")
            return json.dumps(icons, indent=2, default=str) + rate_limit_note
    except Exception as e:
        logger.error(f"Failed to get category icons: {e}")
        return f"Error getting category icons: {str(e)}"


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
