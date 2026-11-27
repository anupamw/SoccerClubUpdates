import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from app.core import football_data
from app.core.config import get_settings


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "accounts.sqlite3"))
    monkeypatch.setenv("API_STATS_DB_PATH", str(tmp_path / "api_calls.db"))
    monkeypatch.setenv("FOOTBALL_DATA_API_TOKEN", "test-token")
    monkeypatch.setenv("DATA_COLLECTION_MODE", "once")
    football_data.initialize_league_database()
    return tmp_path / "accounts.sqlite3"


def provider_payloads():
    team_names = [
        "Arsenal",
        "Aston Villa",
        "Bournemouth",
        "Brentford",
        "Brighton",
        "Burnley",
        "Chelsea",
        "Crystal Palace",
        "Everton",
        "Fulham",
        "Leeds United",
        "Liverpool",
        "Manchester City",
        "Manchester United",
        "Newcastle United",
        "Nottingham Forest",
        "Sunderland",
        "Tottenham Hotspur",
        "West Ham United",
        "Wolverhampton Wanderers",
    ]
    return {
        "/competitions/PL": {
            "id": 2021,
            "code": "PL",
            "name": "Premier League",
            "area": {"name": "England"},
            "currentSeason": {
                "id": 733,
                "startDate": "2026-08-01",
                "endDate": "2027-05-31",
                "currentMatchday": 20,
            },
        },
        "/competitions/PL/teams?season=2026": {
            "teams": [
                {"id": team_id, "name": name, "shortName": name, "tla": name[:3].upper()}
                for team_id, name in enumerate(team_names, start=1)
            ]
        },
        "/competitions/PL/standings?season=2026": {
            "standings": [
                {
                    "type": "TOTAL",
                    "table": [
                        {
                            "position": position,
                            "team": {"id": position},
                            "playedGames": 10,
                            "won": 10 - position // 2,
                            "draw": 1,
                            "lost": position // 2,
                            "points": 30 - position,
                            "goalsFor": 30 - position,
                            "goalsAgainst": position,
                            "goalDifference": 30 - (2 * position),
                            "form": "W,W,D,W,W",
                        }
                        for position in range(1, 21)
                    ],
                }
            ]
        },
        "/competitions/PL/matches?season=2026": {
            "matches": [
                {
                    "id": 9001,
                    "competition": {"id": 2021},
                    "season": {"id": 733},
                    "matchday": 10,
                    "utcDate": "2026-11-25T18:00:00Z",
                    "status": "FINISHED",
                    "homeTeam": {"id": 1, "name": "Arsenal"},
                    "awayTeam": {"id": 2, "name": "Manchester United"},
                    "venue": "Emirates Stadium",
                    "score": {"fullTime": {"home": 2, "away": 1}},
                    "goals": [
                        {
                            "minute": 12,
                            "injuryTime": None,
                            "type": "PENALTY",
                            "team": {"id": 1, "name": "Arsenal"},
                            "scorer": {"id": 99, "name": "Test Scorer"},
                        }
                    ],
                }
            ]
        },
    }


class FakeResponse:
    status = 200
    headers = {"X-Requests-Available": "9"}

    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return self.data


def test_collection_normalizes_data_and_is_idempotent(database, monkeypatch):
    payloads = provider_payloads()
    requests = []

    def fake_urlopen(request, timeout):
        assert isinstance(request, Request)
        assert request.get_header("X-auth-token") == "test-token"
        requests.append(request.full_url)
        path = request.full_url.removeprefix("https://api.football-data.org/v4")
        return FakeResponse(payloads[path])

    monkeypatch.setattr(football_data, "urlopen", fake_urlopen)
    monkeypatch.setattr(football_data.time, "sleep", lambda _: None)

    assert football_data.collect_league()["status"] == "success"
    assert football_data.collect_league()["status"] == "success"
    data = football_data.get_league_data()

    assert len(requests) == 8
    assert data["competition"]["name"] == "Premier League"
    assert len(data["teams"]) == 20
    assert [row["team_name"] for row in data["standings"][:2]] == ["Arsenal", "Aston Villa"]
    assert len(data["matches"]) == 1
    assert data["matches"][0]["utc_date"] == "2026-11-25T18:00:00+00:00"
    assert data["matches"][0]["home_score"] == 2
    assert data["events"] == []
    assert data["collection_status"]["freshness"] == "fresh"
    assert data["collection_status"]["provider_calls_last_hour"] == 8

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM match_events").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM standings").fetchone()[0] == 40


def test_exact_event_time_is_preserved(database):
    match, events = football_data._normalize_match(
        {
            "id": 1,
            "competition": {"id": 2021},
            "season": {"id": 2026},
            "utcDate": "2026-11-25T18:00:00Z",
            "homeTeam": {"id": 1, "name": "Home"},
            "awayTeam": {"id": 2, "name": "Away"},
            "goals": [{"minute": 12, "utcDate": "2026-11-25T18:11:35Z", "scorer": {"name": "Player"}}],
        },
        include_events=True,
    )
    assert match["utc_date"] == "2026-11-25T18:00:00+00:00"
    assert events[0]["occurred_at_utc"] == "2026-11-25T18:11:35+00:00"
    assert events[0]["timestamp_source"] == "provider_timestamp"
    assert events[0]["timestamp_precision"] == "exact"


def test_minute_only_event_is_marked_approximate(database):
    _, events = football_data._normalize_match(
        {
            "id": 2,
            "competition": {"id": 2021},
            "season": {"id": 2026},
            "utcDate": "2026-11-25T18:00:00Z",
            "homeTeam": {"id": 1, "name": "Home"},
            "awayTeam": {"id": 2, "name": "Away"},
            "goals": [{"minute": 12, "type": "PENALTY", "team": {"id": 1, "name": "Home"}}],
        },
        include_events=True,
    )
    assert events[0]["occurred_at_utc"] == "2026-11-25T18:12:00+00:00"
    assert events[0]["timestamp_source"] == "elapsed_minute_from_kickoff"
    assert events[0]["timestamp_precision"] == "approximate"
    assert events[0]["minute"] == 12
    assert events[0]["period"] == "first_half"

    _, first_half_event = football_data._normalize_match(
        {
            "id": 3,
            "competition": {"id": 2021},
            "season": {"id": 2026},
            "utcDate": "2026-11-25T18:00:00Z",
            "homeTeam": {"id": 1, "name": "Home"},
            "awayTeam": {"id": 2, "name": "Away"},
            "goals": [{"minute": 45, "injuryTime": 3}],
        },
        include_events=True,
    )
    assert first_half_event[0]["period"] == "first_half"


def test_shared_hourly_budget_is_atomic_and_persistent(database):
    now = datetime(2026, 11, 26, 12, tzinfo=UTC)

    def reserve(index):
        return football_data.reserve_provider_call(f"matches/{index}", "matches", now)

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(reserve, range(12)))

    assert sum(result is not None for result in results) == 9
    assert football_data.get_call_budget(now) == {"limit": 9, "used": 9, "remaining": 0}
    football_data.initialize_league_database()
    assert football_data.get_call_budget(now)["used"] == 9
    assert football_data.reserve_provider_call("matches/retry", "matches", now) is None


def test_budget_uses_rolling_hour_not_calendar_hour(database):
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    assert football_data.reserve_provider_call("matches/old", "matches", now - timedelta(hours=1, seconds=1))
    for index in range(9):
        assert football_data.reserve_provider_call(f"matches/{index}", "matches", now)
    assert football_data.get_call_budget(now)["remaining"] == 0


def test_missing_token_is_reported_without_request(database, monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_TOKEN")
    monkeypatch.setattr(football_data, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected provider call"))

    result = football_data.collect_league()

    assert result["status"] == "error"
    assert "not configured" in result["error_summary"]
    assert football_data.get_call_budget()["used"] == 0
    status = football_data.get_league_data()["collection_status"]
    assert status["freshness"] == "unavailable"
    assert status["last_run_status"] == "error"


def test_provider_failures_are_sanitized_and_retries_count(database, monkeypatch):
    attempts = 0

    def fail_request(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise HTTPError("https://api.football-data.org/v4/competitions/PL", 503, "failed", {}, None)

    monkeypatch.setattr(football_data, "urlopen", fail_request)
    monkeypatch.setattr(football_data.time, "sleep", lambda _: None)
    result = football_data.collect_league()

    assert attempts == 2
    assert result["status"] == "error"
    assert result["error_summary"] == "Provider request failed for competition (HTTP503)"
    assert football_data.get_call_budget()["used"] == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM provider_calls WHERE outcome = 'error'").fetchone()[0] == 2


def test_failed_refresh_keeps_cache_and_marks_it_stale(database, monkeypatch):
    payloads = provider_payloads()

    def successful_request(request, timeout):
        path = request.full_url.removeprefix("https://api.football-data.org/v4")
        return FakeResponse(payloads[path])

    monkeypatch.setattr(football_data, "urlopen", successful_request)
    monkeypatch.setattr(football_data.time, "sleep", lambda _: None)
    assert football_data.collect_league()["status"] == "success"
    monkeypatch.setattr(
        football_data,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError("https://api.football-data.org/v4/competitions/PL", 503, "failed", {}, None)
        ),
    )

    assert football_data.collect_league()["status"] == "error"
    data = football_data.get_league_data()
    assert len(data["matches"]) == 1
    assert data["collection_status"]["freshness"] == "stale"
    assert data["collection_status"]["last_run_status"] == "error"
    assert "HTTP503" in data["collection_status"]["error_summary"]


def test_exhausted_budget_defers_provider_request(database, monkeypatch):
    now = datetime.now(UTC)
    for index in range(9):
        assert football_data.reserve_provider_call(f"matches/{index}", "matches", now)
    monkeypatch.setattr(football_data, "urlopen", lambda *_args, **_kwargs: pytest.fail("unexpected provider call"))

    with pytest.raises(football_data.CallBudgetExhausted, match="deferred"):
        football_data._request_json("competitions/PL", "competition")


def test_recent_success_prevents_unnecessary_daily_refresh(database):
    run_id, _ = football_data._new_sync_run()
    football_data._finish_sync_run(run_id, "success", 42)
    assert football_data.has_recent_success()


def test_collection_modes_and_daily_interval(database, monkeypatch):
    monkeypatch.delenv("DATA_COLLECTION_MODE", raising=False)
    assert get_settings().data_collection_mode == "once"

    from app import collector

    monkeypatch.setenv("DATA_COLLECTION_MODE", "once")
    monkeypatch.setattr(collector, "has_successful_collection", lambda: True)
    monkeypatch.setattr(collector, "collect_league", lambda: pytest.fail("once mode should not reschedule"))
    monkeypatch.setattr(collector.time, "sleep", lambda _: (_ for _ in ()).throw(RuntimeError("stop once mode")))
    with pytest.raises(RuntimeError, match="stop once mode"):
        collector.run()

    monkeypatch.setenv("DATA_COLLECTION_MODE", "daily")
    calls = []

    def collect():
        calls.append("run")
        return {"status": "success"}

    def stop_after_one_interval(seconds):
        assert seconds == 4 * 60 * 60
        if len(calls) == 2:
            raise RuntimeError("stop test loop")

    monkeypatch.setattr(collector, "collect_league", collect)
    monkeypatch.setattr(collector, "has_recent_success", lambda: False)
    monkeypatch.setattr(collector.time, "sleep", stop_after_one_interval)
    with pytest.raises(RuntimeError, match="stop test loop"):
        collector.run()
    assert calls == ["run", "run"]


def test_collection_lock_coalesces_concurrent_runs(database):
    owner = "first"
    assert football_data._acquire_collection_lock(owner)
    assert not football_data._acquire_collection_lock("second")
    football_data._release_collection_lock(owner)
    assert football_data._acquire_collection_lock("second")
