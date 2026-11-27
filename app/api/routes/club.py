from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.football_data import get_league_data

router = APIRouter(prefix="/api/v1", tags=["club"])


class ClubSelection(BaseModel):
    league: str
    club: str


@router.get("/clubs")
def clubs() -> dict:
    data = get_league_data()
    return {
        "leagues": (
            [{"name": data["competition"]["name"], "clubs": [team["name"] for team in data["teams"]]}]
            if data["competition"] is not None
            else []
        ),
        "collection_status": data["collection_status"],
    }


@router.post("/club/select")
def select_club(selection: ClubSelection) -> dict:
    data = get_league_data()
    team = next((item for item in data["teams"] if item["name"] == selection.club), None)
    if data["competition"] is None or data["competition"]["name"] != selection.league or team is None:
        raise HTTPException(status_code=404, detail="That club is not available yet")
    return {"club": team["name"], "league": data["competition"]["name"], "crest": team["crest"]}


@router.get("/club/feed")
def club_feed() -> dict:
    data = get_league_data()
    return {
        "updates": [],
        "available": False,
        "message": "Club news is not collected by this data source",
        "collection_status": data["collection_status"],
    }
