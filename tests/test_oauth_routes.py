"""Tests for OAuth 2.0 routes."""
from urllib.parse import parse_qs, urlparse
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from sure_mcp_server.auth_db import AuthDB
from sure_mcp_server.oauth_routes import make_oauth_routes


@pytest.fixture
def client_and_db(tmp_path):
    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    routes = make_oauth_routes(db, "https://example.com")
    app = Starlette(routes=routes)
    return TestClient(app, raise_server_exceptions=True), db


def test_discovery_returns_endpoints(client_and_db):
    client, _ = client_and_db
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["authorization_endpoint"] == "https://example.com/authorize"
    assert data["token_endpoint"] == "https://example.com/token"


def test_authorize_get_returns_form(client_and_db):
    client, _ = client_and_db
    response = client.get(
        "/authorize",
        params={"state": "abc", "redirect_uri": "https://claude.ai/callback", "client_id": "X-Sure-Api-Key"},
    )
    assert response.status_code == 200
    assert "Sure API Key" in response.text
    assert 'name="api_key"' in response.text


def test_full_oauth_flow(client_and_db):
    client, db = client_and_db
    # POST authorize
    response = client.post(
        "/authorize",
        data={
            "api_key": "my-sure-key",
            "redirect_uri": "https://claude.ai/callback",
            "state": "xyz",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "client_id": "X-Sure-Api-Key",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    code = parse_qs(urlparse(location).query)["code"][0]

    # POST token
    response = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": code},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert db.get_api_key_for_token(data["access_token"]) == "my-sure-key"


def test_token_with_invalid_code_returns_400(client_and_db):
    client, _ = client_and_db
    response = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": "bad-code"},
    )
    assert response.status_code == 400


def test_missing_api_key_returns_400(client_and_db):
    client, _ = client_and_db
    response = client.post(
        "/authorize",
        data={"redirect_uri": "https://claude.ai/callback", "state": "xyz", "api_key": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
