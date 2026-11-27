from datetime import UTC, datetime, timedelta

from app.core.football_data import _finish_sync_run, _new_sync_run, _persist_snapshot, initialize_league_database


def seed() -> None:
    initialize_league_database()
    team_names = [
        "Arsenal",
        "Aston Villa",
        "Bournemouth",
        "Brentford",
        "Brighton & Hove Albion",
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
    teams = [
        {"id": team_id, "name": name, "short_name": name, "tla": name[:3].upper(), "crest": None}
        for team_id, name in enumerate(team_names, start=1)
    ]
    standings = [
        {
            "team_id": team["id"],
            "position": position,
            "played_games": 10,
            "won": max(0, 10 - position // 2),
            "draw": 2,
            "lost": position // 2,
            "points": 30 - position,
            "goals_for": 30 - position,
            "goals_against": position,
            "goal_difference": 30 - (2 * position),
            "form": "W,W,D,L,W",
        }
        for position, team in enumerate(teams, start=1)
    ]
    now = datetime.now(UTC)
    matches = []
    for index in range(10):
        kickoff = now - timedelta(days=1) if index == 0 else now + timedelta(days=index)
        matches.append(
            {
                "id": 9000 + index,
                "competition_id": 2021,
                "season_id": 2026,
                "matchday": 10 + index,
                "utc_date": kickoff.isoformat(),
                "status": "FINISHED" if index == 0 else "SCHEDULED",
                "home_team_id": teams[index]["id"],
                "home_team_name": teams[index]["name"],
                "away_team_id": teams[index + 10]["id"],
                "away_team_name": teams[index + 10]["name"],
                "venue": f"Test Ground {index + 1}",
                "home_score": 2 if index == 0 else None,
                "away_score": 1 if index == 0 else None,
                "last_updated": now.isoformat(),
                "events": [],
            }
        )
    competition = {
        "id": 2021,
        "code": "PL",
        "name": "Premier League",
        "emblem": None,
        "area": "England",
        "season": {
            "id": 2026,
            "start_date": "2026-08-01",
            "end_date": "2027-05-31",
            "current_matchday": 20,
            "winner_name": None,
        },
    }
    _persist_snapshot(competition, teams, standings, matches)
    run_id, _ = _new_sync_run()
    _finish_sync_run(run_id, "success", 52)


if __name__ == "__main__":
    seed()
