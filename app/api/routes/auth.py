import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core import accounts, football_data
from app.core.config import get_settings
from app.core.security import get_authenticated_subject


router = APIRouter(prefix="/auth", tags=["authentication"])


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateAccountRequest(BaseModel):
    favorite_team_id: int | None = Field(default=None, gt=0)
    timezone_name: str | None = Field(default=None, min_length=1, max_length=64)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountResponse(BaseModel):
    username: str
    can_change_password: bool
    favorite_team_id: int | None
    timezone_name: str


class TimeZoneOptionsResponse(BaseModel):
    timezones: list[str]


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest) -> dict[str, str]:
    settings = get_settings()
    if secrets.compare_digest(payload.username.encode(), settings.demo_username.encode()):
        raise HTTPException(status_code=409, detail="This username is reserved")
    if not accounts.create_account(payload.username, payload.password):
        raise HTTPException(status_code=409, detail="Username is already registered")
    return {"username": payload.username}


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    username_matches = secrets.compare_digest(payload.username.encode(), settings.demo_username.encode())
    password_matches = secrets.compare_digest(payload.password.encode(), settings.demo_password.encode())
    account = accounts.get_account(payload.username)
    valid = (username_matches and password_matches) or (
        account is not None and accounts.verify_password(payload.password, account.password_hash)
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": payload.username, "exp": now + timedelta(minutes=settings.token_expiry_minutes), "iat": now},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return LoginResponse(access_token=token)


@router.get("/timezones", response_model=TimeZoneOptionsResponse)
def timezones(_subject: str = Depends(get_authenticated_subject)) -> TimeZoneOptionsResponse:
    return TimeZoneOptionsResponse(timezones=sorted(available_timezones() | {"UTC"}))


@router.get("/account", response_model=AccountResponse)
def account(subject: str = Depends(get_authenticated_subject)) -> AccountResponse:
    return AccountResponse(
        username=subject,
        can_change_password=accounts.get_account(subject) is not None,
        favorite_team_id=accounts.get_favorite_team_id(subject),
        timezone_name=accounts.get_timezone_name(subject),
    )


@router.patch("/account", response_model=AccountResponse)
def update_account(
    payload: UpdateAccountRequest,
    subject: str = Depends(get_authenticated_subject),
) -> AccountResponse:
    updated_fields = payload.model_fields_set
    if "favorite_team_id" in updated_fields and payload.favorite_team_id is not None:
        league = football_data.get_league_data()
        if league["competition"] is None or not league["teams"]:
            raise HTTPException(status_code=503, detail="League data is unavailable; try again after collection")
        if not any(team["id"] == payload.favorite_team_id for team in league["teams"]):
            raise HTTPException(status_code=422, detail="Favourite team is not in the current league data")
    timezone_name = None
    if "timezone_name" in updated_fields:
        timezone_name = payload.timezone_name or "UTC"
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(status_code=422, detail="Timezone must be a valid IANA timezone") from None
    if "favorite_team_id" in updated_fields:
        accounts.set_favorite_team_id(subject, payload.favorite_team_id)
    if timezone_name is not None:
        accounts.set_timezone_name(subject, timezone_name)
    return AccountResponse(
        username=subject,
        can_change_password=accounts.get_account(subject) is not None,
        favorite_team_id=accounts.get_favorite_team_id(subject),
        timezone_name=accounts.get_timezone_name(subject),
    )


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, subject: str = Depends(get_authenticated_subject)) -> dict[str, str]:
    account = accounts.get_account(subject)
    if account is None:
        raise HTTPException(status_code=403, detail="Password changes are unavailable for the demo account")
    if not accounts.verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if secrets.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(status_code=400, detail="New password must be different from the current password")
    if not accounts.update_password(subject, payload.new_password):
        raise HTTPException(status_code=404, detail="Account no longer exists")
    return {"message": "Password updated"}
