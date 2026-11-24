import sqlite3
from contextlib import closing

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import initialize_api_call_database


DEBUG_STATS_PATH = "/api/v1/debugstats"
router = APIRouter(prefix="/api/v1", tags=["debug"])


@router.get("/debugstats")
def debug_stats() -> dict:
    initialize_api_call_database()
    with closing(sqlite3.connect(get_settings().api_stats_db_path)) as connection:
        total = connection.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
        rows = connection.execute(
            "SELECT method, path, status_code, COUNT(*) FROM api_calls GROUP BY method, path, status_code ORDER BY path"
        ).fetchall()
    return {
        "total_calls": total,
        "by_endpoint": [
            {"method": method, "path": path, "status_code": status_code, "count": count}
            for method, path, status_code, count in rows
        ],
    }
