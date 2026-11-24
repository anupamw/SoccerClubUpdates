import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.config import get_settings


def initialize_api_call_database() -> None:
    path = Path(get_settings().api_stats_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS api_calls (method TEXT NOT NULL, path TEXT NOT NULL, status_code INTEGER NOT NULL)")


def record_api_call(method: str, path: str, status_code: int) -> None:
    database_path = Path(get_settings().api_stats_db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS api_calls (method TEXT NOT NULL, path TEXT NOT NULL, status_code INTEGER NOT NULL)")
        connection.execute("INSERT INTO api_calls VALUES (?, ?, ?)", (method, path, status_code))
