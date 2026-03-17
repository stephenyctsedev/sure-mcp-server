"""Tests for AuthMiddleware."""
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from sure_mcp_server.auth_db import AuthDB


def make_test_app(tmp_path):
    from sure_mcp_server.server import AuthMiddleware, _api_key_var

    captured = {}

    async def endpoint(request: Request) -> JSONResponse:
        captured["key"] = _api_key_var.get()
        return JSONResponse({"ok": True})

    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    inner = Starlette(routes=[Route("/test", endpoint)])
    app = AuthMiddleware(inner, auth_db=db)
    return TestClient(app, raise_server_exceptions=False), db, captured


def test_bearer_token_sets_api_key(tmp_path):
    client, db, captured = make_test_app(tmp_path)
    token = db.create_token("bearer-key")
    response = client.get("/test", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert captured["key"] == "bearer-key"


def test_x_sure_api_key_header_sets_api_key(tmp_path):
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test", headers={"X-Sure-Api-Key": "header-key"})
    assert response.status_code == 200
    assert captured["key"] == "header-key"


def test_env_var_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SURE_API_KEY", "env-key")
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test")
    assert response.status_code == 200
    assert captured["key"] == "env-key"


def test_no_auth_returns_401(tmp_path, monkeypatch):
    monkeypatch.delenv("SURE_API_KEY", raising=False)
    client, db, captured = make_test_app(tmp_path)
    response = client.get("/test")
    assert response.status_code == 401


def test_oauth_paths_bypass_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("SURE_API_KEY", raising=False)
    from sure_mcp_server.server import AuthMiddleware

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    db = AuthDB(str(tmp_path / "test.db"))
    db.initialize()
    inner = Starlette(routes=[
        Route("/.well-known/oauth-authorization-server", endpoint),
        Route("/authorize", endpoint, methods=["GET", "POST"]),
        Route("/token", endpoint, methods=["POST"]),
    ])
    app = AuthMiddleware(inner, auth_db=db)
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
    assert client.get("/authorize").status_code == 200
    assert client.post("/token", data={}).status_code == 200
