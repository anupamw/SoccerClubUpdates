from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/v1", tags=["club"])


class ClubSelection(BaseModel):
    league: str
    club: str


CLUBS = {
    ("Premier League", "Manchester United"): {
        "club": "Manchester United",
        "league": "Premier League",
        "accent": "#da291c",
        "position": 8,
        "points": 42,
        "played": 30,
        "form": ["win", "draw", "win", "loss", "win"],
        "next_match": {"competition": "Premier League", "opponent": "Liverpool", "date": "Sunday, 16:30", "venue": "Old Trafford"},
        "updates": [
            {"category": "Team news", "title": "Squad preparing for the next Premier League match", "time": "42 min ago"},
            {"category": "Match preview", "title": "Manchester United host Liverpool this weekend", "time": "2 hours ago"},
            {"category": "Academy", "title": "Youth team reaches the semi-final", "time": "Yesterday"},
        ],
    }
}


@router.get("/clubs")
def clubs() -> dict:
    return {"leagues": [{"name": "Premier League", "clubs": ["Manchester United"]}]}


@router.post("/club/select")
def select_club(selection: ClubSelection) -> dict:
    club = CLUBS.get((selection.league, selection.club))
    if club is None:
        raise HTTPException(status_code=404, detail="That club is not available yet")
    return club


@router.get("/club/feed")
def club_feed() -> dict:
    return CLUBS[("Premier League", "Manchester United")]
