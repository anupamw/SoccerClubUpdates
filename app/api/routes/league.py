from fastapi import APIRouter

from app.core.football_data import get_league_data


router = APIRouter(prefix="/api/v1/league", tags=["league"])


@router.get("")
def league() -> dict:
    return get_league_data()


@router.get("/matches")
def matches() -> dict:
    data = get_league_data()
    return {
        "competition": data["competition"],
        "season": data["season"],
        "matches": data["matches"],
        "collection_status": data["collection_status"],
    }


@router.get("/standings")
def standings() -> dict:
    data = get_league_data()
    return {
        "competition": data["competition"],
        "season": data["season"],
        "standings": data["standings"],
        "collection_status": data["collection_status"],
    }
