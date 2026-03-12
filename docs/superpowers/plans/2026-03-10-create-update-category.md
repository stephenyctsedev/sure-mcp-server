# create_category + update_category Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `create_category` and `update_category` MCP tools to the Sure MCP server.

**Architecture:** Both tools follow the POST/PATCH with wrapped JSON payload pattern used by `create_transaction` and `update_transaction`. Optional-field guards use `is not None` (matching `update_transaction`'s style — not `create_transaction`'s truthiness guards, which would silently drop empty strings). Tools are inserted in `server.py` after `get_category` (line 516), before `sync_accounts` (line 519), to keep category tools grouped. Tests are written first (TDD) in a new file `tests/test_tools_category.py`.

**Tech Stack:** Python 3.12, FastMCP, httpx, pytest, pytest-mock, unittest.mock

---

## Chunk 1: create_category (TDD)

### Task 1: Write failing tests for create_category

**Files:**
- Create: `tests/test_tools_category.py`

- [ ] **Step 1: Create the test file with tests for create_category**

Create `tests/test_tools_category.py`:

```python
"""Tests for create_category and update_category MCP tools."""
import json
import unittest.mock as mock

import pytest


def make_mock_client(status_code: int, json_body: dict) -> mock.MagicMock:
    """Helper: return a mock httpx.Client context manager with a canned response."""
    mock_response = mock.MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = json_body

    mock_client = mock.MagicMock()
    mock_client.__enter__ = mock.Mock(return_value=mock_client)
    mock_client.__exit__ = mock.Mock(return_value=False)
    mock_client.post.return_value = mock_response
    mock_client.patch.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# create_category
# ---------------------------------------------------------------------------

class TestCreateCategory:
    def test_create_category_required_fields_only(self, monkeypatch):
        """Should POST to /api/v1/categories with name + classification only."""
        from sure_mcp_server.server import create_category

        expected_data = {"id": "cat-1", "name": "Groceries", "classification": "expense"}
        mock_client = make_mock_client(201, {"category": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_category(name="Groceries", classification="expense")

        mock_client.post.assert_called_once_with(
            "/api/v1/categories",
            json={"category": {"name": "Groceries", "classification": "expense"}},
        )
        assert json.loads(result) == {"category": expected_data}

    def test_create_category_all_optional_fields(self, monkeypatch):
        """Should include color, icon, parent_id in payload when provided."""
        from sure_mcp_server.server import create_category

        expected_data = {
            "id": "cat-2",
            "name": "Fast Food",
            "classification": "expense",
            "color": "#ff0000",
            "icon": "burger",
            "parent_id": "cat-1",
        }
        mock_client = make_mock_client(201, {"category": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_category(
                name="Fast Food",
                classification="expense",
                color="#ff0000",
                icon="burger",
                parent_id="cat-1",
            )

        mock_client.post.assert_called_once_with(
            "/api/v1/categories",
            json={
                "category": {
                    "name": "Fast Food",
                    "classification": "expense",
                    "color": "#ff0000",
                    "icon": "burger",
                    "parent_id": "cat-1",
                }
            },
        )
        assert json.loads(result) == {"category": expected_data}

    def test_create_category_omits_none_optional_fields(self, monkeypatch):
        """Optional fields that are None should NOT appear in the payload."""
        from sure_mcp_server.server import create_category

        mock_client = make_mock_client(201, {"id": "cat-3"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            create_category(name="Salary", classification="income")

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]["category"]
        assert "color" not in payload
        assert "icon" not in payload
        assert "parent_id" not in payload

    def test_create_category_api_error_returns_error_string(self, monkeypatch):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import create_category

        mock_client = make_mock_client(422, {})
        mock_client.post.return_value.status_code = 422
        mock_client.post.return_value.text = "Unprocessable Entity"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_category(name="Bad", classification="expense")

        assert result.startswith("Error creating category:")
```

- [ ] **Step 2: Run the tests to verify they fail**

```
pytest tests/test_tools_category.py::TestCreateCategory -v
```

Expected: `FAILED` — `ImportError` or `AttributeError` because `create_category` doesn't exist yet.

---

### Task 2: Implement create_category

**Files:**
- Modify: `src/sure_mcp_server/server.py` — insert after line 517 (after `get_category`)

- [ ] **Step 3: Insert the create_category tool into server.py**

In `server.py`, insert the following block **after the closing of `get_category` at line 516, before the `@mcp.tool()` decorator for `sync_accounts` at line 519**. Add a blank line before and after the new block:

```python
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
```

- [ ] **Step 4: Run the create_category tests to verify they pass**

```
pytest tests/test_tools_category.py::TestCreateCategory -v
```

Expected: All 4 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tools_category.py src/sure_mcp_server/server.py
git commit -m "feat: add create_category MCP tool"
```

---

## Chunk 2: update_category (TDD)

### Task 3: Write failing tests for update_category

**Files:**
- Modify: `tests/test_tools_category.py` — append tests below existing ones

- [ ] **Step 4: Append update_category tests to the test file**

Append to `tests/test_tools_category.py`:

```python
# ---------------------------------------------------------------------------
# update_category
# ---------------------------------------------------------------------------

class TestUpdateCategory:
    def test_update_category_single_field(self, monkeypatch):
        """Should PATCH /api/v1/categories/{id} with only the changed field."""
        from sure_mcp_server.server import update_category

        expected_data = {"id": "cat-1", "name": "Renamed"}
        mock_client = make_mock_client(200, {"category": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_category(category_id="cat-1", name="Renamed")

        mock_client.patch.assert_called_once_with(
            "/api/v1/categories/cat-1",
            json={"category": {"name": "Renamed"}},
        )
        assert json.loads(result) == {"category": expected_data}

    def test_update_category_all_fields(self, monkeypatch):
        """Should PATCH with all provided fields."""
        from sure_mcp_server.server import update_category

        expected_data = {"id": "cat-1", "name": "Updated"}
        mock_client = make_mock_client(200, {"category": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_category(
                category_id="cat-1",
                name="Updated",
                classification="income",
                color="#00ff00",
                icon="star",
                parent_id="cat-0",
            )

        call_kwargs = mock_client.patch.call_args
        payload = call_kwargs.kwargs["json"]["category"]
        assert payload == {
            "name": "Updated",
            "classification": "income",
            "color": "#00ff00",
            "icon": "star",
            "parent_id": "cat-0",
        }

    def test_update_category_omits_none_fields(self, monkeypatch):
        """None optional fields must not appear in the PATCH payload."""
        from sure_mcp_server.server import update_category

        mock_client = make_mock_client(200, {"id": "cat-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_category(category_id="cat-1", name="Only Name")

        payload = mock_client.patch.call_args.kwargs["json"]["category"]
        assert "classification" not in payload
        assert "color" not in payload
        assert "icon" not in payload
        assert "parent_id" not in payload

    def test_update_category_no_optional_fields_sends_empty_payload(self, monkeypatch):
        """Calling with only category_id should PATCH with empty category dict."""
        from sure_mcp_server.server import update_category

        mock_client = make_mock_client(200, {"id": "cat-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_category(category_id="cat-1")

        payload = mock_client.patch.call_args.kwargs["json"]["category"]
        assert payload == {}

    def test_update_category_api_error_returns_error_string(self, monkeypatch):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import update_category

        mock_client = make_mock_client(404, {})
        mock_client.patch.return_value.status_code = 404
        mock_client.patch.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_category(category_id="nonexistent")

        assert result.startswith("Error updating category:")
```

- [ ] **Step 5: Run the update_category tests to verify they fail**

```
pytest tests/test_tools_category.py::TestUpdateCategory -v
```

Expected: `FAILED` — `ImportError` or `AttributeError` because `update_category` doesn't exist yet.

---

### Task 4: Implement update_category

**Files:**
- Modify: `src/sure_mcp_server/server.py` — insert after `create_category`

- [ ] **Step 6: Insert the update_category tool into server.py**

In `server.py`, insert the following block immediately after the closing of `create_category`:

```python
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
        parent_id: New parent category ID for nesting
    """
    try:
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
                payload["parent_id"] = parent_id

            response = client.patch(
                f"/api/v1/categories/{category_id}",
                json={"category": payload}
            )
            data = handle_response(response)

            logger.info(f"✅ Updated category {category_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to update category: {e}")
        return f"Error updating category: {str(e)}"
```

- [ ] **Step 7: Run all category tests to verify they pass**

```
pytest tests/test_tools_category.py -v
```

Expected: All 9 tests `PASSED`.

- [ ] **Step 8: Run the full test suite to check for regressions**

```
pytest tests/ -v
```

Expected: All tests `PASSED`.

- [ ] **Step 9: Commit**

```bash
git add tests/test_tools_category.py src/sure_mcp_server/server.py
git commit -m "feat: add update_category MCP tool"
```
