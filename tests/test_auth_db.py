"""Tests for AuthDB SQLite token store."""
import sqlite3
import time
import pytest
from sure_mcp_server.auth_db import AuthDB


@pytest.fixture
def db(tmp_path):
    d = AuthDB(str(tmp_path / "test.db"))
    d.initialize()
    return d


def test_create_and_exchange_code(db):
    code = db.create_auth_code("my-api-key", "state123")
    assert len(code) == 64  # secrets.token_hex(32) = 64 hex chars
    api_key = db.exchange_code(code)
    assert api_key == "my-api-key"


def test_code_is_single_use(db):
    code = db.create_auth_code("key", "state")
    db.exchange_code(code)
    assert db.exchange_code(code) is None


def test_expired_code_returns_none(db):
    code = db.create_auth_code("key", "state")
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE auth_codes SET expires_at = ? WHERE code = ?",
            (int(time.time()) - 1, code)
        )
    assert db.exchange_code(code) is None


def test_create_and_lookup_token(db):
    token = db.create_token("my-api-key")
    assert len(token) == 64
    assert db.get_api_key_for_token(token) == "my-api-key"


def test_unknown_token_returns_none(db):
    assert db.get_api_key_for_token("nonexistent") is None
