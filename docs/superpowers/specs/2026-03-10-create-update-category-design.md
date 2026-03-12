# Design: create_category + update_category MCP Tools

**Date:** 2026-03-10
**Branch:** feature/create-update-category

## Overview

Add two new MCP tools to the Sure MCP Server: `create_category` and `update_category`. These follow the same patterns as the existing `create_transaction` and `update_transaction` tools.

## Reference Patterns

- **Data structure:** `get_categories` / `get_category` tools
- **Implementation pattern:** `create_transaction` (POST + wrapped payload) and `update_transaction` (PATCH + wrapped payload)
- **Optional field schema:** `Optional[str] = None` — FastMCP/Pydantic renders this as `anyOf: [{type}, {type: null}]` with `default: null`

## Tools

### create_category

**Endpoint:** `POST /api/v1/categories`
**Payload wrapper:** `{"category": {...}}`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | Yes | Category name |
| `classification` | `str` | Yes | `"income"` or `"expense"` |
| `color` | `Optional[str]` | No | Color string (e.g. hex code) |
| `icon` | `Optional[str]` | No | Icon identifier |
| `parent_id` | `Optional[str]` | No | Parent category ID for nesting |

Optional fields are added to the payload only if `is not None`.

### update_category

**Endpoint:** `PATCH /api/v1/categories/{category_id}`
**Payload wrapper:** `{"category": {...}}`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `category_id` | `str` | Yes | ID of category to update |
| `name` | `Optional[str]` | No | New category name |
| `classification` | `Optional[str]` | No | New classification |
| `color` | `Optional[str]` | No | New color string |
| `icon` | `Optional[str]` | No | New icon identifier |
| `parent_id` | `Optional[str]` | No | New parent category ID |

All fields optional; only non-None fields sent in payload.

## Placement

Both tools are inserted in `server.py` after `get_category` (line ~516), keeping category-related tools grouped together.

## Error Handling

Consistent with all other tools: try/except wrapping, `handle_response()` for HTTP errors, logger with emoji prefix, user-friendly error string returned on failure.
