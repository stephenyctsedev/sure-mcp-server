"""SQLite-backed store for OAuth auth codes and access tokens."""
import os
import secrets
import sqlite3
import time
from pathlib import Path


class AuthDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AUTH_DB_PATH", "/app/data/auth.db")

    def initialize(self) -> None:
        """Create tables if they don't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code       TEXT PRIMARY KEY,
                    api_key    TEXT NOT NULL,
                    state      TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    token      TEXT PRIMARY KEY,
                    api_key    TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)

    def create_auth_code(self, api_key: str, state: str) -> str:
        """Generate a single-use auth code valid for 10 minutes."""
        code = secrets.token_hex(32)
        expires_at = int(time.time()) + 600
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_codes VALUES (?, ?, ?, ?)",
                (code, api_key, state, expires_at),
            )
        return code

    def exchange_code(self, code: str) -> str | None:
        """Exchange auth code for api_key. Deletes code (single use). Returns None if invalid/expired."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM auth_codes WHERE expires_at < ?", (int(time.time()),)
            )
            row = conn.execute(
                "SELECT api_key FROM auth_codes WHERE code = ?", (code,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM auth_codes WHERE code = ?", (code,))
                return row[0]
        return None

    def create_token(self, api_key: str) -> str:
        """Issue a long-lived access token for an api_key."""
        token = secrets.token_hex(32)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO tokens VALUES (?, ?, ?)",
                (token, api_key, int(time.time())),
            )
        return token

    def get_api_key_for_token(self, token: str) -> str | None:
        """Look up the api_key for a Bearer token. Returns None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT api_key FROM tokens WHERE token = ?", (token,)
            ).fetchone()
        return row[0] if row else None
