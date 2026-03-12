# delete_category Tool Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `delete_category` MCP tool that calls `DELETE /api/v1/categories/:id`, mirroring `delete_transaction` exactly.

**Architecture:** Single function added to `server.py` after `update_category`. Tests added to the existing `test_tools_category.py` file. No new files created.

**Tech Stack:** Python, FastMCP, httpx, pytest

**Spec:** `docs/superpowers/specs/2026-03-11-delete-category-design.md`

---

## Chunk 1: Branch + TDD Implementation

### Task 1: Create feature branch

**Files:**
- (git only)

- [ ] **Step 1: Create and check out the branch**

```bash
git checkout -b feature/delete-category
```

Expected: `Switched to a new branch 'feature/delete-category'`

---

### Task 2: Write failing tests for `delete_category`

**Files:**
- Modify: `tests/test_tools_category.py`

- [ ] **Step 1: Add a `TestDeleteCategory` class at the end of `tests/test_tools_category.py`**

```python
# ---------------------------------------------------------------------------
# delete_category
# ---------------------------------------------------------------------------

class TestDeleteCategory:
    def _make_delete_client(self, status_code: int, json_body: dict) -> mock.MagicMock:
        """Mock httpx.Client with delete stubbed."""
        mock_response = mock.MagicMock()
        mock_response.status_code = status_code
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = json_body

        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.delete.return_value = mock_response
        return mock_client

    def test_delete_category_calls_correct_endpoint(self):
        """Should DELETE /api/v1/categories/{id}."""
        from sure_mcp_server.server import delete_category

        mock_client = self._make_delete_client(200, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            delete_category(category_id="cat-1")

        mock_client.delete.assert_called_once_with("/api/v1/categories/cat-1")

    def test_delete_category_returns_json_on_success(self):
        """Should return JSON-serialised response on success."""
        from sure_mcp_server.server import delete_category

        expected_data = {"id": "cat-1", "deleted": True}
        mock_client = self._make_delete_client(200, expected_data)

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = delete_category(category_id="cat-1")

        assert json.loads(result) == expected_data

    def test_delete_category_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import delete_category

        mock_client = self._make_delete_client(404, {})
        mock_client.delete.return_value.status_code = 404
        mock_client.delete.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = delete_category(category_id="nonexistent")

        assert result.startswith("Error deleting category:")
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd /c/Users/stephen/Documents/Project/sure-mcp-server
python -m pytest tests/test_tools_category.py::TestDeleteCategory -v
```

Expected: `ImportError` or `AttributeError` — `delete_category` does not exist yet.

---

### Task 3: Implement `delete_category` in `server.py`

**Files:**
- Modify: `src/sure_mcp_server/server.py` (after line 619, after `update_category`)

- [ ] **Step 1: Insert the `delete_category` function after `update_category`**

After the closing of `update_category` (after line 619), add:

```python
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
            data = handle_response(response)

            logger.info(f"✅ Deleted category {category_id}")
            return json.dumps(data, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to delete category: {e}")
        return f"Error deleting category: {str(e)}"
```

- [ ] **Step 2: Run the tests to confirm they pass**

```bash
python -m pytest tests/test_tools_category.py::TestDeleteCategory -v
```

Expected: `3 passed`

- [ ] **Step 3: Run the full test suite to confirm nothing is broken**

```bash
python -m pytest -v
```

Expected: all tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add src/sure_mcp_server/server.py tests/test_tools_category.py docs/superpowers/specs/2026-03-11-delete-category-design.md docs/superpowers/plans/2026-03-11-delete-category.md
git commit -m "feat: add delete_category MCP tool"
```
