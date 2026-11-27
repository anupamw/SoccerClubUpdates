from fastapi import APIRouter

from app.api.routes import auth, club, debug_stats, health, league


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(club.router)
api_router.include_router(league.router)
api_router.include_router(debug_stats.router)
