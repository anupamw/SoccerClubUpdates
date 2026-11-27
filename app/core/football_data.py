import hashlib
import json
import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.core.config import get_settings


HOURLY_CALL_LIMIT = 9
CALL_WINDOW = timedelta(hours=1)
REQUEST_ATTEMPTS = 2
REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_REFRESH_INTERVAL_SECONDS = 4 * 60 * 60
DATASET = "premier-league-current-season"


class ProviderError(RuntimeError):
    pass


class CallBudgetExhausted(ProviderError):
    pass


def _database_path() -> Path:
    return Path(get_settings().database_path)


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _utc_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def initialize_league_database() -> None:
    with closing(_connect()) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS competitions (
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                emblem TEXT,
                area TEXT,
                current_season_id INTEGER,
                last_synced_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY,
                competition_id INTEGER NOT NULL REFERENCES competitions(id),
                start_date TEXT,
                end_date TEXT,
                current_matchday INTEGER,
                winner_name TEXT
            );
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT,
                tla TEXT,
                crest TEXT
            );
            CREATE TABLE IF NOT EXISTS standings (
                competition_id INTEGER NOT NULL,
                season_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                collected_at TEXT NOT NULL,
                position INTEGER NOT NULL,
                played_games INTEGER NOT NULL,
                won INTEGER NOT NULL,
                draw INTEGER NOT NULL,
                lost INTEGER NOT NULL,
                points INTEGER NOT NULL,
                goals_for INTEGER NOT NULL,
                goals_against INTEGER NOT NULL,
                goal_difference INTEGER NOT NULL,
                form TEXT,
                PRIMARY KEY (competition_id, season_id, team_id, collected_at)
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY,
                competition_id INTEGER NOT NULL,
                season_id INTEGER NOT NULL,
                matchday INTEGER,
                utc_date TEXT,
                status TEXT NOT NULL,
                home_team_id INTEGER,
                home_team_name TEXT NOT NULL,
                away_team_id INTEGER,
                away_team_name TEXT NOT NULL,
                venue TEXT,
                home_score INTEGER,
                away_score INTEGER,
                last_updated TEXT
            );
            CREATE TABLE IF NOT EXISTS match_events (
                id TEXT PRIMARY KEY,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                event_type TEXT NOT NULL,
                team_id INTEGER,
                team_name TEXT,
                player_id INTEGER,
                player_name TEXT,
                assist_player_id INTEGER,
                assist_player_name TEXT,
                minute INTEGER,
                injury_time INTEGER,
                period TEXT,
                occurred_at_utc TEXT NOT NULL,
                timestamp_source TEXT NOT NULL,
                timestamp_precision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_runs (
                id TEXT PRIMARY KEY,
                dataset TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                error_summary TEXT
            );
            CREATE TABLE IF NOT EXISTS provider_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                category TEXT NOT NULL,
                request_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                http_status INTEGER,
                retry_after TEXT,
                requests_available TEXT
            );
            CREATE INDEX IF NOT EXISTS provider_calls_request_at_idx
                ON provider_calls(request_at);
            CREATE TABLE IF NOT EXISTS collection_lock (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                lease_until TEXT NOT NULL
            );
            """
        )


def reserve_provider_call(endpoint: str, category: str, now: datetime | None = None) -> int | None:
    timestamp = _utc_iso(now)
    cutoff = _utc_iso((now or datetime.now(UTC)) - CALL_WINDOW)
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        count = connection.execute(
            "SELECT COUNT(*) FROM provider_calls WHERE request_at >= ?",
            (cutoff,),
        ).fetchone()[0]
        if count >= HOURLY_CALL_LIMIT:
            connection.rollback()
            return None
        cursor = connection.execute(
            """INSERT INTO provider_calls (endpoint, category, request_at, outcome)
               VALUES (?, ?, ?, 'pending')""",
            (endpoint, category, timestamp),
        )
        connection.commit()
        return int(cursor.lastrowid)


def finish_provider_call(
    call_id: int,
    outcome: str,
    http_status: int | None = None,
    retry_after: str | None = None,
    requests_available: str | None = None,
) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """UPDATE provider_calls
               SET outcome = ?, http_status = ?, retry_after = ?, requests_available = ?
               WHERE id = ?""",
            (outcome, http_status, retry_after, requests_available, call_id),
        )


def get_call_budget(now: datetime | None = None) -> dict[str, int]:
    cutoff = _utc_iso((now or datetime.now(UTC)) - CALL_WINDOW)
    with closing(_connect()) as connection:
        used = connection.execute(
            "SELECT COUNT(*) FROM provider_calls WHERE request_at >= ?",
            (cutoff,),
        ).fetchone()[0]
    return {"limit": HOURLY_CALL_LIMIT, "used": int(used), "remaining": max(0, HOURLY_CALL_LIMIT - used)}


def _acquire_collection_lock(owner: str, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    timestamp = _utc_iso(current_time)
    lease_until = _utc_iso(current_time + timedelta(minutes=10))
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT owner, lease_until FROM collection_lock WHERE name = ?",
            (DATASET,),
        ).fetchone()
        if row is not None and row["lease_until"] > timestamp:
            connection.rollback()
            return False
        connection.execute(
            """INSERT INTO collection_lock (name, owner, lease_until) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET owner = excluded.owner, lease_until = excluded.lease_until""",
            (DATASET, owner, lease_until),
        )
        connection.commit()
        return True


def _release_collection_lock(owner: str) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute("DELETE FROM collection_lock WHERE name = ? AND owner = ?", (DATASET, owner))


def _new_sync_run() -> tuple[str, str]:
    run_id = str(uuid4())
    started_at = _utc_iso()
    with closing(_connect()) as connection, connection:
        connection.execute(
            "INSERT INTO sync_runs (id, dataset, started_at, status) VALUES (?, ?, ?, 'running')",
            (run_id, DATASET, started_at),
        )
    return run_id, started_at


def _finish_sync_run(run_id: str, status: str, record_count: int = 0, error_summary: str | None = None) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute(
            """UPDATE sync_runs
               SET completed_at = ?, status = ?, record_count = ?, error_summary = ?
               WHERE id = ?""",
            (_utc_iso(), status, record_count, error_summary, run_id),
        )


def _safe_header(headers: Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None else None
    if value is None:
        return None
    value = str(value).strip()
    return value[:32] if value.isascii() and all(char.isalnum() or char in ".,:- " for char in value) else None


def _request_json(endpoint: str, category: str) -> dict[str, Any]:
    settings = get_settings()
    url = f"{settings.football_data_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    for attempt in range(REQUEST_ATTEMPTS):
        call_id = reserve_provider_call(endpoint, category)
        if call_id is None:
            raise CallBudgetExhausted("Provider call budget exhausted; collection deferred")
        request = Request(url, headers={"X-Auth-Token": settings.football_data_api_token})
        status = None
        retry_after = None
        available = None
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read()
                status = getattr(response, "status", 200)
                retry_after = _safe_header(response.headers, "Retry-After")
                available = _safe_header(response.headers, "X-Requests-Available")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Provider returned an invalid response")
            finish_provider_call(call_id, "success", status, retry_after, available)
            return payload
        except HTTPError as error:
            finish_provider_call(
                call_id,
                "error",
                error.code,
                _safe_header(error.headers, "Retry-After"),
                _safe_header(error.headers, "X-Requests-Available"),
            )
            error_type = f"HTTP{error.code}"
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            finish_provider_call(call_id, "error", status, retry_after, available)
            error_type = type(error).__name__
        if attempt + 1 < REQUEST_ATTEMPTS:
            time.sleep(min(2**attempt, 5))
    raise ProviderError(f"Provider request failed for {category} ({error_type})")


def _required_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ProviderError(f"Provider response is missing {key}")
    return value


def _normalize_competition(data: dict[str, Any]) -> dict[str, Any]:
    season = data.get("currentSeason") or {}
    if not isinstance(season, dict) or not isinstance(data.get("id"), int) or not isinstance(season.get("id"), int):
        raise ProviderError("Provider competition response is missing current-season identifiers")
    area = data.get("area") or {}
    winner = season.get("winner") or {}
    return {
        "id": data["id"],
        "code": str(data.get("code") or ""),
        "name": str(data.get("name") or "Premier League"),
        "emblem": data.get("emblem"),
        "area": str(area.get("name") or ""),
        "season": {
            "id": season["id"],
            "start_date": season.get("startDate"),
            "end_date": season.get("endDate"),
            "current_matchday": season.get("currentMatchday"),
            "winner_name": winner.get("name"),
        },
    }


def _normalize_team(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _required_int(data, "id"),
        "name": str(data.get("name") or ""),
        "short_name": data.get("shortName"),
        "tla": data.get("tla"),
        "crest": data.get("crest"),
    }


def _normalize_standings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for standing_group in payload.get("standings", []):
        if standing_group.get("type") != "TOTAL":
            continue
        for item in standing_group.get("table", []):
            team = item.get("team") or {}
            result.append(
                {
                    "team_id": _required_int(team, "id"),
                    "position": _required_int(item, "position"),
                    "played_games": int(item.get("playedGames") or 0),
                    "won": int(item.get("won") or 0),
                    "draw": int(item.get("draw") or 0),
                    "lost": int(item.get("lost") or 0),
                    "points": int(item.get("points") or 0),
                    "goals_for": int(item.get("goalsFor") or 0),
                    "goals_against": int(item.get("goalsAgainst") or 0),
                    "goal_difference": int(item.get("goalDifference") or 0),
                    "form": item.get("form"),
                }
            )
    return result


def _event_period(minute: int | None) -> str | None:
    if minute is None:
        return None
    if minute <= 45:
        return "first_half"
    if minute <= 90:
        return "second_half"
    if minute <= 120:
        return "extra_time"
    return "penalties"


def _normalize_match(
    match: dict[str, Any],
    include_events: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}
    kickoff = match.get("utcDate")
    kickoff_utc = _utc_iso(_parse_utc(kickoff)) if isinstance(kickoff, str) else None
    normalized = {
        "id": _required_int(match, "id"),
        "competition_id": _required_int(match.get("competition") or {}, "id"),
        "season_id": _required_int(match.get("season") or {}, "id"),
        "matchday": match.get("matchday"),
        "utc_date": kickoff_utc,
        "status": str(match.get("status") or "SCHEDULED"),
        "home_team_id": home.get("id"),
        "home_team_name": str(home.get("name") or "Unknown team"),
        "away_team_id": away.get("id"),
        "away_team_name": str(away.get("name") or "Unknown team"),
        "venue": match.get("venue"),
        "home_score": full_time.get("home"),
        "away_score": full_time.get("away"),
        "last_updated": (
            _utc_iso(_parse_utc(match["lastUpdated"]))
            if isinstance(match.get("lastUpdated"), str)
            else None
        ),
    }
    events: list[dict[str, Any]] = []
    for event in (match.get("goals") or []) if include_events else []:
        minute = event.get("minute")
        if not isinstance(minute, int):
            continue
        injury_time = event.get("injuryTime") if isinstance(event.get("injuryTime"), int) else None
        team = event.get("team") or {}
        scorer = event.get("scorer") or {}
        assist = event.get("assist") or {}
        exact_time = event.get("utcDate") or event.get("occurredAt")
        if isinstance(exact_time, str):
            occurred_at = _utc_iso(_parse_utc(exact_time))
            timestamp_source = "provider_timestamp"
            timestamp_precision = "exact"
        elif kickoff is not None:
            occurred_at = _utc_iso(_parse_utc(kickoff) + timedelta(minutes=minute + (injury_time or 0)))
            timestamp_source = "elapsed_minute_from_kickoff"
            timestamp_precision = "approximate"
        else:
            continue
        identity = event.get("id")
        if not isinstance(identity, (str, int)):
            fingerprint = "|".join(
                (
                    str(normalized["id"]),
                    str(event.get("type") or "goal"),
                    str(minute),
                    str(injury_time),
                    str(team.get("id")),
                    str(scorer.get("id")),
                )
            )
            identity = hashlib.sha256(fingerprint.encode()).hexdigest()
        events.append(
            {
                "id": str(identity),
                "match_id": normalized["id"],
                "event_type": str(event.get("type") or "goal"),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "player_id": scorer.get("id"),
                "player_name": scorer.get("name"),
                "assist_player_id": assist.get("id"),
                "assist_player_name": assist.get("name"),
                "minute": minute,
                "injury_time": injury_time,
                "period": str(event.get("period") or _event_period(minute)),
                "occurred_at_utc": occurred_at,
                "timestamp_source": timestamp_source,
                "timestamp_precision": timestamp_precision,
            }
        )
    return normalized, events


def _persist_snapshot(
    competition: dict[str, Any],
    teams: list[dict[str, Any]],
    standings: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> int:
    season = competition["season"]
    collected_at = _utc_iso()
    records = 0
    with closing(_connect()) as connection, connection:
        connection.execute(
            """INSERT INTO competitions (id, code, name, emblem, area, current_season_id, last_synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name,
               emblem=excluded.emblem, area=excluded.area, current_season_id=excluded.current_season_id,
               last_synced_at=excluded.last_synced_at""",
            (
                competition["id"], competition["code"], competition["name"], competition["emblem"],
                competition["area"], season["id"], collected_at,
            ),
        )
        connection.execute(
            """INSERT INTO seasons (id, competition_id, start_date, end_date, current_matchday, winner_name)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET competition_id=excluded.competition_id,
               start_date=excluded.start_date, end_date=excluded.end_date,
               current_matchday=excluded.current_matchday, winner_name=excluded.winner_name""",
            (
                season["id"], competition["id"], season["start_date"], season["end_date"],
                season["current_matchday"], season["winner_name"],
            ),
        )
        for team in teams:
            connection.execute(
                """INSERT INTO teams (id, name, short_name, tla, crest) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, short_name=excluded.short_name,
                   tla=excluded.tla, crest=excluded.crest""",
                (team["id"], team["name"], team["short_name"], team["tla"], team["crest"]),
            )
        for row in standings:
            connection.execute(
                """INSERT OR IGNORE INTO standings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    competition["id"], season["id"], row["team_id"], collected_at, row["position"],
                    row["played_games"], row["won"], row["draw"], row["lost"], row["points"],
                    row["goals_for"], row["goals_against"], row["goal_difference"], row["form"],
                ),
            )
        event_count = 0
        for match in matches:
            connection.execute(
                """INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET competition_id=excluded.competition_id,
                   season_id=excluded.season_id, matchday=excluded.matchday, utc_date=excluded.utc_date,
                   status=excluded.status, home_team_id=excluded.home_team_id,
                   home_team_name=excluded.home_team_name, away_team_id=excluded.away_team_id,
                   away_team_name=excluded.away_team_name, venue=excluded.venue,
                   home_score=excluded.home_score, away_score=excluded.away_score,
                   last_updated=excluded.last_updated""",
                (
                    match["id"], match["competition_id"], match["season_id"], match["matchday"],
                    match["utc_date"], match["status"], match["home_team_id"], match["home_team_name"],
                    match["away_team_id"], match["away_team_name"], match["venue"], match["home_score"],
                    match["away_score"], match["last_updated"],
                ),
            )
            for event in match["events"]:
                connection.execute(
                    """INSERT OR IGNORE INTO match_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["id"], event["match_id"], event["event_type"], event["team_id"], event["team_name"],
                        event["player_id"], event["player_name"], event["assist_player_id"],
                        event["assist_player_name"], event["minute"], event["injury_time"], event["period"],
                        event["occurred_at_utc"], event["timestamp_source"], event["timestamp_precision"],
                    ),
                )
                event_count += 1
        records = 2 + len(teams) + len(standings) + len(matches) + event_count
    return records


def _load_latest_collection() -> sqlite3.Row | None:
    with closing(_connect()) as connection:
        return connection.execute(
            "SELECT * FROM sync_runs WHERE dataset = ? ORDER BY started_at DESC LIMIT 1",
            (DATASET,),
        ).fetchone()


def has_successful_collection() -> bool:
    with closing(_connect()) as connection:
        return connection.execute(
            "SELECT 1 FROM sync_runs WHERE dataset = ? AND status = 'success' LIMIT 1",
            (DATASET,),
        ).fetchone() is not None


def has_recent_success(max_age: timedelta = timedelta(seconds=DEFAULT_REFRESH_INTERVAL_SECONDS)) -> bool:
    with closing(_connect()) as connection:
        row = connection.execute(
            """SELECT completed_at FROM sync_runs
               WHERE dataset = ? AND status = 'success'
               ORDER BY completed_at DESC LIMIT 1""",
            (DATASET,),
        ).fetchone()
    return row is not None and datetime.now(UTC) - _parse_utc(row["completed_at"]) < max_age


def collect_league() -> dict[str, Any]:
    initialize_league_database()
    owner = str(uuid4())
    if not _acquire_collection_lock(owner):
        return {"status": "in_progress", "record_count": 0}
    run_id, _ = _new_sync_run()
    try:
        settings = get_settings()
        if not settings.football_data_api_token:
            raise ProviderError("FOOTBALL_DATA_API_TOKEN is not configured")
        code = settings.football_data_competition_code
        competition_payload = _request_json(f"competitions/{code}", "competition")
        competition = _normalize_competition(competition_payload)
        start_date = competition["season"]["start_date"]
        if not isinstance(start_date, str) or len(start_date) < 4 or not start_date[:4].isdigit():
            raise ProviderError("Provider competition response is missing the current-season start year")
        season_filter = start_date[:4]
        teams_payload = _request_json(f"competitions/{code}/teams?season={season_filter}", "teams")
        standings_payload = _request_json(f"competitions/{code}/standings?season={season_filter}", "standings")
        matches_payload = _request_json(f"competitions/{code}/matches?season={season_filter}", "matches")
        teams = [_normalize_team(item) for item in teams_payload.get("teams", [])]
        standings = _normalize_standings(standings_payload)
        matches: list[dict[str, Any]] = []
        for match_data in matches_payload.get("matches", []):
            match, events = _normalize_match(match_data, include_events=True)
            match["events"] = events
            matches.append(match)
        team_ids = {team["id"] for team in teams}
        standing_team_ids = {row["team_id"] for row in standings}
        if len(teams) != 20 or len(standings) != 20 or team_ids != standing_team_ids:
            raise ProviderError("Provider returned incomplete Premier League team or standings data")
        record_count = _persist_snapshot(competition, teams, standings, matches)
        _finish_sync_run(run_id, "success", record_count)
        return {"status": "success", "record_count": record_count}
    except ProviderError as error:
        _finish_sync_run(run_id, "error", error_summary=str(error)[:200])
        return {"status": "error", "record_count": 0, "error_summary": str(error)[:200]}
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        message = f"Invalid provider response ({type(error).__name__})"
        _finish_sync_run(run_id, "error", error_summary=message)
        return {"status": "error", "record_count": 0, "error_summary": message}
    finally:
        _release_collection_lock(owner)


def get_league_data() -> dict[str, Any]:
    initialize_league_database()
    with closing(_connect()) as connection:
        competition = connection.execute("SELECT * FROM competitions ORDER BY last_synced_at DESC LIMIT 1").fetchone()
        season = None
        teams: list[dict[str, Any]] = []
        standings: list[dict[str, Any]] = []
        matches: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        if competition is not None:
            season = connection.execute("SELECT * FROM seasons WHERE id = ?", (competition["current_season_id"],)).fetchone()
            if season is not None:
                teams = [
                    dict(row)
                    for row in connection.execute(
                        """SELECT DISTINCT t.* FROM teams t JOIN standings s ON s.team_id = t.id
                           WHERE s.competition_id = ? AND s.season_id = ? ORDER BY t.name""",
                        (competition["id"], season["id"]),
                    )
                ]
                standings = [
                    dict(row)
                    for row in connection.execute(
                        """SELECT s.*, t.name AS team_name, t.crest AS team_crest
                           FROM standings s JOIN teams t ON t.id = s.team_id
                           WHERE s.competition_id = ? AND s.season_id = ?
                             AND s.collected_at = (
                               SELECT MAX(latest.collected_at) FROM standings latest
                               WHERE latest.competition_id = s.competition_id
                                 AND latest.season_id = s.season_id AND latest.team_id = s.team_id
                             )
                           ORDER BY s.position""",
                        (competition["id"], season["id"]),
                    )
                ]
                matches = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM matches WHERE competition_id = ? AND season_id = ? ORDER BY utc_date, id",
                        (competition["id"], season["id"]),
                    )
                ]
                events = [
                    dict(row)
                    for row in connection.execute(
                        """SELECT e.* FROM match_events e JOIN matches m ON m.id = e.match_id
                           WHERE m.competition_id = ? AND m.season_id = ?
                           ORDER BY e.occurred_at_utc, e.id""",
                        (competition["id"], season["id"]),
                    )
                ]
        latest = _load_latest_collection()
    success = None
    if latest is not None and latest["status"] == "success":
        success = latest
    else:
        with closing(_connect()) as connection:
            success = connection.execute(
                "SELECT * FROM sync_runs WHERE dataset = ? AND status = 'success' ORDER BY started_at DESC LIMIT 1",
                (DATASET,),
            ).fetchone()
    now = datetime.now(UTC)
    if success is None:
        freshness = "unavailable"
    elif now - _parse_utc(success["completed_at"]) > timedelta(hours=30):
        freshness = "stale"
    elif latest is not None and latest["status"] != "success":
        freshness = "stale"
    else:
        freshness = "fresh"
    budget = get_call_budget()
    status = {
        "freshness": freshness,
        "mode": get_settings().data_collection_mode,
        "last_updated": success["completed_at"] if success is not None else None,
        "last_run_status": latest["status"] if latest is not None else "not_run",
        "error_summary": latest["error_summary"] if latest is not None else None,
        "records_in_last_run": latest["record_count"] if latest is not None else 0,
        "provider_calls_last_hour": budget["used"],
        "provider_calls_remaining": budget["remaining"],
    }
    return {
        "competition": dict(competition) if competition is not None else None,
        "season": dict(season) if season is not None else None,
        "teams": teams,
        "standings": standings,
        "matches": matches,
        "events": events,
        "collection_status": status,
    }
