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


def test_club_feed_is_restricted_to_epl_manchester_united(client):
    clubs = client.get("/api/v1/clubs").json()
    assert clubs == {"leagues": [{"name": "Premier League", "clubs": ["Manchester United"]}]}
    selection = client.post("/api/v1/club/select", json={"league": "Premier League", "club": "Manchester United"})
    assert selection.status_code == 200
    assert selection.json()["club"] == "Manchester United"
    assert client.post("/api/v1/club/select", json={"league": "La Liga", "club": "Barcelona"}).status_code == 404
    feed = client.get("/api/v1/club/feed").json()
    assert len(feed["updates"]) == 3


def test_dashboard_and_stats(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Soccer Club Updates" in page.text
    assert "Manchester United" in page.text
    stats = client.get("/api/v1/debugstats").json()
    assert "total_calls" in stats
