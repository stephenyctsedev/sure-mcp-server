"""Tests for create_category, update_category, and delete_category MCP tools."""
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
    mock_client.delete.return_value = mock_response
    mock_client.get.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# create_category
# ---------------------------------------------------------------------------

class TestCreateCategory:
    def test_create_category_required_fields_only(self):
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

    def test_create_category_all_optional_fields(self):
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

    def test_create_category_omits_none_optional_fields(self):
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

    def test_create_category_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import create_category

        mock_client = make_mock_client(422, {})
        mock_client.post.return_value.status_code = 422
        mock_client.post.return_value.text = "Unprocessable Entity"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_category(name="Bad", classification="expense")

        assert result.startswith("Error creating category:")

    def test_create_category_invalid_classification_returns_error(self):
        """Should return error immediately for invalid classification without API call."""
        from sure_mcp_server.server import create_category

        result = create_category(name="Test", classification="invalid")

        assert result == "Error creating category: classification must be 'income' or 'expense'"


# ---------------------------------------------------------------------------
# update_category
# ---------------------------------------------------------------------------

class TestUpdateCategory:
    def test_update_category_single_field(self):
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

    def test_update_category_all_fields(self):
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
        assert json.loads(result) == {"category": expected_data}

    def test_update_category_omits_none_fields(self):
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

    def test_update_category_no_optional_fields_sends_empty_payload(self):
        """Calling with only category_id should PATCH with empty category dict."""
        from sure_mcp_server.server import update_category

        mock_client = make_mock_client(200, {"id": "cat-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_category(category_id="cat-1")

        payload = mock_client.patch.call_args.kwargs["json"]["category"]
        assert payload == {}

    def test_update_category_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import update_category

        mock_client = make_mock_client(404, {})
        mock_client.patch.return_value.status_code = 404
        mock_client.patch.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_category(category_id="nonexistent")

        assert result.startswith("Error updating category:")

    def test_update_category_invalid_classification_returns_error(self):
        """Should return error immediately for invalid classification without API call."""
        from sure_mcp_server.server import update_category

        result = update_category(category_id="cat-1", classification="bad")

        assert result == "Error updating category: classification must be 'income' or 'expense'"


# ---------------------------------------------------------------------------
# delete_category
# ---------------------------------------------------------------------------

class TestDeleteCategory:
    def test_delete_category_calls_correct_endpoint(self):
        """Should DELETE /api/v1/categories/{id}."""
        from sure_mcp_server.server import delete_category

        mock_client = make_mock_client(200, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            delete_category(category_id="cat-1")

        mock_client.delete.assert_called_once_with("/api/v1/categories/cat-1")

    def test_delete_category_returns_json_on_success(self):
        """Should return JSON-serialised response on success."""
        from sure_mcp_server.server import delete_category

        expected_data = {"id": "cat-1", "deleted": True}
        mock_client = make_mock_client(200, expected_data)

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = delete_category(category_id="cat-1")

        assert json.loads(result) == expected_data

    def test_delete_category_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import delete_category

        mock_client = make_mock_client(404, {})
        mock_client.delete.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = delete_category(category_id="nonexistent")

        assert result.startswith("Error deleting category:")

    def test_delete_category_url_uses_provided_id(self):
        """Should interpolate category_id into the DELETE URL."""
        from sure_mcp_server.server import delete_category

        mock_client = make_mock_client(200, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            delete_category(category_id="cat-99")

        mock_client.delete.assert_called_once_with("/api/v1/categories/cat-99")


# ---------------------------------------------------------------------------
# get_category_icons
# ---------------------------------------------------------------------------

class TestGetCategoryIcons:
    def test_get_category_icons_returns_icons_array(self):
        """Should GET /api/v1/categories/icons and return the icons list."""
        from sure_mcp_server.server import get_category_icons

        icons = ["ambulance", "apple", "award"]
        mock_client = make_mock_client(200, {"icons": icons})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_category_icons()

        mock_client.get.assert_called_once_with("/api/v1/categories/icons")
        assert json.loads(result) == icons

    def test_get_category_icons_fallback_when_no_icons_key(self):
        """Should fall back to data.get('data') when 'icons' key absent."""
        from sure_mcp_server.server import get_category_icons

        icons = ["star", "home"]
        mock_client = make_mock_client(200, {"data": icons})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_category_icons()

        assert json.loads(result) == icons

    def test_get_category_icons_fallback_raw_list(self):
        """Should handle API returning a plain list directly (no wrapper key)."""
        from sure_mcp_server.server import get_category_icons

        icons = ["car", "plane"]
        mock_client = make_mock_client(200, icons)

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_category_icons()

        assert json.loads(result) == icons

    def test_get_category_icons_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import get_category_icons

        mock_client = make_mock_client(500, {})
        mock_client.get.return_value.status_code = 500
        mock_client.get.return_value.text = "Internal Server Error"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_category_icons()

        assert result.startswith("Error getting category icons:")
