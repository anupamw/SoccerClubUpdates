from fastapi.testclient import TestClient
import pytest

from app.core.football_data import _persist_snapshot
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.setenv("API_STATS_DB_PATH", str(tmp_path / "api_calls.db"))
    with TestClient(app) as test_client:
        yield test_client


def seed_league() -> None:
    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "Arsenal", "tla": "ARS", "crest": "https://example.test/arsenal.svg"},
        {"id": 2, "name": "Aston Villa", "short_name": "Aston Villa", "tla": "AVL", "crest": None},
    ]
    standings = [
        {
            "team_id": team["id"],
            "position": index,
            "played_games": 0,
            "won": 0,
            "draw": 0,
            "lost": 0,
            "points": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "form": None,
        }
        for index, team in enumerate(teams, start=1)
    ]
    _persist_snapshot(
        {
            "id": 2021,
            "code": "PL",
            "name": "Premier League",
            "emblem": None,
            "area": "England",
            "season": {
                "id": 2026,
                "start_date": "2026-08-01",
                "end_date": "2027-05-31",
                "current_matchday": 1,
                "winner_name": None,
            },
        },
        teams,
        standings,
        [],
    )


def signup_and_get_headers(client, username):
    password = "valid-password"
    assert client.post("/auth/signup", json={"username": username, "password": password}).status_code == 201
    token = client.post("/auth/login", json={"username": username, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    assert client.get("/health/live").json() == {"status": "alive"}


def test_signup_login_account_password_change(client):
    username = "soccer-fan"
    old_password = "old-password"
    new_password = "new-password"
    created = client.post("/auth/signup", json={"username": username, "password": old_password})
    assert created.status_code == 201
    login = client.post("/auth/login", json={"username": username, "password": old_password})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/account", headers=headers).json()["username"] == username
    changed = client.post("/auth/change-password", headers=headers, json={"current_password": old_password, "new_password": new_password})
    assert changed.status_code == 200
    assert client.post("/auth/login", json={"username": username, "password": old_password}).status_code == 401
    assert client.post("/auth/login", json={"username": username, "password": new_password}).status_code == 200


def test_favorite_team_preferences_are_authenticated_and_isolated(client):
    seed_league()
    first_headers = signup_and_get_headers(client, "first-fan")
    second_headers = signup_and_get_headers(client, "second-fan")

    assert client.get("/auth/account", headers=first_headers).json()["favorite_team_id"] is None
    assert client.patch(
        "/auth/account",
        headers=first_headers,
        json={"favorite_team_id": 1},
    ).json()["favorite_team_id"] == 1
    assert client.patch(
        "/auth/account",
        headers=second_headers,
        json={"favorite_team_id": 2},
    ).json()["favorite_team_id"] == 2
    assert client.get("/auth/account", headers=first_headers).json()["favorite_team_id"] == 1
    assert client.get("/auth/account", headers=second_headers).json()["favorite_team_id"] == 2

    cleared = client.patch(
        "/auth/account",
        headers=first_headers,
        json={"favorite_team_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["favorite_team_id"] is None


def test_favorite_team_requires_cached_known_team(client):
    headers = signup_and_get_headers(client, "team-fan")
    unavailable = client.patch(
        "/auth/account",
        headers=headers,
        json={"favorite_team_id": 1},
    )
    assert unavailable.status_code == 503
    assert "League data is unavailable" in unavailable.json()["detail"]

    seed_league()
    invalid = client.patch(
        "/auth/account",
        headers=headers,
        json={"favorite_team_id": 999},
    )
    assert invalid.status_code == 422
    assert "not in the current league data" in invalid.json()["detail"]


def test_demo_user_can_save_favorite_team(client):
    seed_league()
    from app.core.config import get_settings

    settings = get_settings()
    login = client.post(
        "/auth/login",
        json={"username": settings.demo_username, "password": settings.demo_password},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    saved = client.patch(
        "/auth/account",
        headers=headers,
        json={"favorite_team_id": 1},
    )
    assert saved.status_code == 200
    assert saved.json()["can_change_password"] is False
    assert client.get("/auth/account", headers=headers).json()["favorite_team_id"] == 1


def test_favorite_team_endpoints_require_authentication(client):
    assert client.get("/auth/account").status_code == 401
    assert client.patch("/auth/account", json={"favorite_team_id": None}).status_code == 401


def test_league_endpoints_use_collected_data_and_news_is_out_of_scope(client):
    clubs = client.get("/api/v1/clubs").json()
    assert clubs["leagues"] == []
    assert clubs["collection_status"]["freshness"] == "unavailable"
    assert client.get("/api/v1/league").json()["collection_status"]["freshness"] == "unavailable"
    assert client.get("/api/v1/league/matches").json()["matches"] == []
    assert client.get("/api/v1/league/standings").json()["standings"] == []
    selection = client.post("/api/v1/club/select", json={"league": "Premier League", "club": "Manchester United"})
    assert selection.status_code == 404
    feed = client.get("/api/v1/club/feed").json()
    assert feed["updates"] == []
    assert feed["available"] is False


def test_dashboard_and_stats(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Soccer Club Updates" in page.text
    assert "Premier League standings" in page.text
    stats = client.get("/api/v1/debugstats").json()
    assert "total_calls" in stats
