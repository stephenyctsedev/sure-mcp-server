# Design: `get_category_icons` MCP Tool

**Date:** 2026-03-11
**Branch:** feature/get-categories-icons

## Summary

Add a new MCP tool `get_category_icons` that wraps the `GET /api/v1/categories/icons` endpoint. This lets Claude enumerate valid icon identifiers before calling `create_category` or `update_category`.

## Endpoint

```
GET /api/v1/categories/icons
```

**Response shape:**
```json
{ "icons": ["ambulance", "apple", "award", ...] }
```

## Tool Design

**Name:** `get_category_icons`
**No parameters** — the endpoint takes none.
**Returns:** JSON array of icon name strings (extracted from `data["icons"]`).

### Implementation

```python
@mcp.tool()
def get_category_icons() -> str:
    """Get all available icon identifiers that can be used when creating or updating a category."""
    try:
        with get_client() as client:
            response = client.get("/api/v1/categories/icons")
            data = handle_response(response)
            icons = data.get("icons") or data.get("data") or data
            logger.info(f"✅ Retrieved {len(icons) if isinstance(icons, list) else 'unknown'} icons")
            return json.dumps(icons, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to get category icons: {e}")
        return f"Error getting category icons: {str(e)}"
```

Follows the same pattern as `get_categories()`: extract the key array, log count, return `json.dumps`.

## Testing

Three test cases in `tests/test_tools_category.py` (new `TestGetCategoryIcons` class):

1. **Happy path** — mock returns `{"icons": ["ambulance", "apple"]}`, assert result is `json.dumps(["ambulance", "apple"])`
2. **Fallback** — mock returns `{"data": ["x"]}` (no `icons` key), assert result is `json.dumps(["x"])`
3. **API error** — mock returns 500, assert result starts with `"Error getting category icons:"`

## Files Changed

- `src/sure_mcp_server/server.py` — add `get_category_icons` tool after `delete_category`
- `tests/test_tools_category.py` — add `TestGetCategoryIcons` test class
