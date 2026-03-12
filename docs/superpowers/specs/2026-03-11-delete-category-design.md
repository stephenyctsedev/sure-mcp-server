# Design: `delete_category` MCP Tool

**Date:** 2026-03-11
**Status:** Approved

## Summary

Add a `delete_category` MCP tool to the Sure MCP server, following the exact same pattern as `delete_transaction`.

## Tool Spec

- **Name:** `delete_category`
- **Parameter:** `category_id` (str, required) — the ID of the category to delete
- **Endpoint:** `DELETE /api/v1/categories/:id`
- **Returns:** JSON response from the API, or an error string on failure

## Implementation

Single function in `server.py`, placed after `update_category`:

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

## Tests

Added to `tests/test_tools_category.py` as `TestDeleteCategory` class:

1. **Successful delete** — `DELETE /api/v1/categories/{id}` called, JSON response returned
2. **404 API error** — returns `"Error deleting category: ..."` string (no raise)
3. **Correct endpoint** — assert exact URL called

The existing `make_mock_client` stubs `post`/`patch`; delete tests use an inline mock that stubs `delete` instead.

## Pattern Reference

Mirrors `delete_transaction` (server.py:430–447) and `delete_chat` (server.py:737–754) exactly.
