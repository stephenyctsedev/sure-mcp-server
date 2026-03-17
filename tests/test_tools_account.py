"""Tests for get_account, create_account, and update_account MCP tools."""
import json
import unittest.mock as mock

import pytest


def make_mock_client(status_code: int, json_body) -> mock.MagicMock:
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
    mock_client.get.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------

class TestGetAccount:
    def test_get_account_calls_correct_endpoint(self):
        """Should GET /api/v1/accounts/{id}."""
        from sure_mcp_server.server import get_account

        expected_data = {"id": "acc-1", "name": "Checking"}
        mock_client = make_mock_client(200, expected_data)

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_account(account_id="acc-1")

        mock_client.get.assert_called_once_with("/api/v1/accounts/acc-1")
        assert json.loads(result) == expected_data

    def test_get_account_returns_json_on_success(self):
        """Should return JSON-serialised response on success."""
        from sure_mcp_server.server import get_account

        expected_data = {"id": "acc-2", "name": "Savings", "balance": 1000.0}
        mock_client = make_mock_client(200, expected_data)

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_account(account_id="acc-2")

        assert json.loads(result) == expected_data

    def test_get_account_not_found_returns_error_string(self):
        """Should return an error string on 404."""
        from sure_mcp_server.server import get_account

        mock_client = make_mock_client(404, {})
        mock_client.get.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = get_account(account_id="nonexistent")

        assert result.startswith("Error getting account:")

    def test_get_account_url_uses_provided_id(self):
        """Should interpolate account_id into the GET URL."""
        from sure_mcp_server.server import get_account

        mock_client = make_mock_client(200, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            get_account(account_id="acc-99")

        mock_client.get.assert_called_once_with("/api/v1/accounts/acc-99")


# ---------------------------------------------------------------------------
# create_account
# ---------------------------------------------------------------------------

class TestCreateAccount:
    def test_create_account_required_fields_only(self):
        """Should POST to /api/v1/accounts with name + accountable_type only."""
        from sure_mcp_server.server import create_account

        expected_data = {"id": "acc-1", "name": "Checking", "accountable_type": "Depository"}
        mock_client = make_mock_client(201, {"account": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_account(name="Checking", accountable_type="Depository")

        mock_client.post.assert_called_once_with(
            "/api/v1/accounts",
            json={"account": {"name": "Checking", "accountable_type": "Depository"}},
        )
        assert json.loads(result) == {"account": expected_data}

    def test_create_account_all_optional_fields(self):
        """Should include balance, currency, institution_name, notes, opening_balance_date when provided."""
        from sure_mcp_server.server import create_account

        expected_data = {
            "id": "acc-2",
            "name": "Savings",
            "accountable_type": "Depository",
            "balance": 500.0,
            "currency": "USD",
            "institution_name": "Big Bank",
            "notes": "My savings",
            "opening_balance_date": "2024-01-01",
        }
        mock_client = make_mock_client(201, {"account": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_account(
                name="Savings",
                accountable_type="Depository",
                balance=500.0,
                currency="USD",
                institution_name="Big Bank",
                notes="My savings",
                opening_balance_date="2024-01-01",
            )

        mock_client.post.assert_called_once_with(
            "/api/v1/accounts",
            json={
                "account": {
                    "name": "Savings",
                    "accountable_type": "Depository",
                    "balance": 500.0,
                    "currency": "USD",
                    "institution_name": "Big Bank",
                    "notes": "My savings",
                    "opening_balance_date": "2024-01-01",
                }
            },
        )
        assert json.loads(result) == {"account": expected_data}

    def test_create_account_omits_none_optional_fields(self):
        """Optional fields that are None should NOT appear in the payload."""
        from sure_mcp_server.server import create_account

        mock_client = make_mock_client(201, {"id": "acc-3"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            create_account(name="Credit Card", accountable_type="CreditCard")

        payload = mock_client.post.call_args.kwargs["json"]["account"]
        assert "balance" not in payload
        assert "currency" not in payload
        assert "institution_name" not in payload
        assert "notes" not in payload
        assert "opening_balance_date" not in payload

    def test_create_account_invalid_accountable_type_returns_error(self):
        """Should return an error string when accountable_type is not a valid PascalCase value."""
        from sure_mcp_server.server import create_account

        mock_client = make_mock_client(201, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_account(name="Test", accountable_type="checking")

        assert result.startswith("Error creating account:")
        assert "accountable_type" in result
        mock_client.post.assert_not_called()

    def test_create_account_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import create_account

        mock_client = make_mock_client(422, {})
        mock_client.post.return_value.status_code = 422
        mock_client.post.return_value.text = "Unprocessable Entity"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = create_account(name="Bad", accountable_type="Depository")

        assert result.startswith("Error creating account:")

    def test_create_account_uses_accountable_type_not_account_type(self):
        """The payload must use 'accountable_type', never 'account_type'."""
        from sure_mcp_server.server import create_account

        mock_client = make_mock_client(201, {"id": "acc-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            create_account(name="Loan", accountable_type="Loan")

        payload = mock_client.post.call_args.kwargs["json"]["account"]
        assert "accountable_type" in payload
        assert "account_type" not in payload
        assert payload["accountable_type"] == "Loan"


# ---------------------------------------------------------------------------
# update_account
# ---------------------------------------------------------------------------

class TestUpdateAccount:
    def test_update_account_single_field(self):
        """Should PATCH /api/v1/accounts/{id} with only the changed field."""
        from sure_mcp_server.server import update_account

        expected_data = {"id": "acc-1", "name": "Renamed"}
        mock_client = make_mock_client(200, {"account": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_account(account_id="acc-1", name="Renamed")

        mock_client.patch.assert_called_once_with(
            "/api/v1/accounts/acc-1",
            json={"account": {"name": "Renamed"}},
        )
        assert json.loads(result) == {"account": expected_data}

    def test_update_account_all_fields(self):
        """Should PATCH with all supported updatable fields."""
        from sure_mcp_server.server import update_account

        expected_data = {"id": "acc-1", "name": "Updated"}
        mock_client = make_mock_client(200, {"account": expected_data})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_account(
                account_id="acc-1",
                name="Updated",
                balance=2000.0,
                institution_name="New Bank",
                notes="Updated notes",
            )

        payload = mock_client.patch.call_args.kwargs["json"]["account"]
        assert payload == {
            "name": "Updated",
            "balance": 2000.0,
            "institution_name": "New Bank",
            "notes": "Updated notes",
        }
        assert json.loads(result) == {"account": expected_data}

    def test_update_account_does_not_send_accountable_type(self):
        """accountable_type is not accepted by update_account (immutable field)."""
        from sure_mcp_server.server import update_account
        import inspect

        sig = inspect.signature(update_account)
        assert "accountable_type" not in sig.parameters
        assert "account_type" not in sig.parameters

    def test_update_account_omits_none_fields(self):
        """None optional fields must not appear in the PATCH payload."""
        from sure_mcp_server.server import update_account

        mock_client = make_mock_client(200, {"id": "acc-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_account(account_id="acc-1", name="Only Name")

        payload = mock_client.patch.call_args.kwargs["json"]["account"]
        assert "account_type" not in payload
        assert "accountable_type" not in payload
        assert "balance" not in payload
        assert "institution_name" not in payload
        assert "notes" not in payload

    def test_update_account_no_optional_fields_sends_empty_payload(self):
        """Calling with only account_id should PATCH with empty account dict."""
        from sure_mcp_server.server import update_account

        mock_client = make_mock_client(200, {"id": "acc-1"})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_account(account_id="acc-1")

        payload = mock_client.patch.call_args.kwargs["json"]["account"]
        assert payload == {}

    def test_update_account_api_error_returns_error_string(self):
        """Should return an error string (not raise) on API failure."""
        from sure_mcp_server.server import update_account

        mock_client = make_mock_client(404, {})
        mock_client.patch.return_value.status_code = 404
        mock_client.patch.return_value.text = "Not Found"

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            result = update_account(account_id="nonexistent")

        assert result.startswith("Error updating account:")

    def test_update_account_url_uses_provided_id(self):
        """Should interpolate account_id into the PATCH URL."""
        from sure_mcp_server.server import update_account

        mock_client = make_mock_client(200, {})

        with mock.patch("sure_mcp_server.server.get_client", return_value=mock_client):
            update_account(account_id="acc-77", name="Test")

        mock_client.patch.assert_called_once_with(
            "/api/v1/accounts/acc-77",
            json={"account": {"name": "Test"}},
        )
