import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str
    demo_username: str
    demo_password: str
    jwt_secret: str
    token_expiry_minutes: int
    database_path: str
    api_stats_db_path: str


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Soccer Club Updates"),
        demo_username=os.getenv("DEMO_USERNAME", "fan"),
        demo_password=os.getenv("DEMO_PASSWORD", "change-me"),
        jwt_secret=os.getenv("JWT_SECRET", "local-development-secret-change-me"),
        token_expiry_minutes=int(os.getenv("TOKEN_EXPIRY_MINUTES", "60")),
        database_path=os.getenv("DATABASE_PATH", "data/accounts.sqlite3"),
        api_stats_db_path=os.getenv("API_STATS_DB_PATH", "data/api_calls.db"),
    )
