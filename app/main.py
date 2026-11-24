from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from starlette.middleware.base import RequestResponseEndpoint

from app.api.router import api_router
from app.api.routes.debug_stats import DEBUG_STATS_PATH
from app.core.config import get_settings
from app.core.database import initialize_api_call_database, record_api_call


static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_api_call_database()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.middleware("http")
async def track_api_calls(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if request.url.path.rstrip("/") == DEBUG_STATS_PATH:
        return await call_next(request)
    try:
        response = await call_next(request)
    except Exception:
        record_api_call(request.method, getattr(request.scope.get("route"), "path", request.url.path), 500)
        raise
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    record_api_call(request.method, path, response.status_code)
    return response
