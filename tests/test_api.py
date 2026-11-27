from fastapi.testclient import TestClient
import pytest

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.setenv("API_STATS_DB_PATH", str(tmp_path / "api_calls.db"))
    with TestClient(app) as test_client:
        yield test_client


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
