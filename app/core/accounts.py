import hashlib
import hmac
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 310_000
_SALT_BYTES = 16


@dataclass(frozen=True)
class Account:
    username: str
    password_hash: str


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != _ALGORITHM or int(iterations) != _ITERATIONS:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(actual, expected)


def _connect() -> sqlite3.Connection:
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
    return connection


def get_account(username: str) -> Account | None:
    with closing(_connect()) as connection:
        row = connection.execute("SELECT username, password_hash FROM accounts WHERE username = ?", (username,)).fetchone()
    return None if row is None else Account(row["username"], row["password_hash"])


def create_account(username: str, password: str) -> bool:
    try:
        with closing(_connect()) as connection, connection:
            connection.execute("INSERT INTO accounts VALUES (?, ?, ?)", (username, hash_password(password), datetime.now(UTC).isoformat()))
    except sqlite3.IntegrityError:
        return False
    return True


def update_password(username: str, password: str) -> bool:
    with closing(_connect()) as connection, connection:
        cursor = connection.execute("UPDATE accounts SET password_hash = ? WHERE username = ?", (hash_password(password), username))
    return cursor.rowcount == 1
