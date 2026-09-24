"""Authentication endpoints (T03 / FR01): login and current-user lookup."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import User
from backend.app.schemas import (
    LoginRequest,
    TokenResponse,
    UserPublic,
)
from backend.app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# A valid bcrypt hash of an unguessable random value. Verifying against it for
# unknown emails keeps the response time of "no such account" equal to
# "wrong password", removing the timing side channel that would otherwise
# allow account enumeration on email.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))

# One generic error for unknown email AND wrong password: no account
# enumeration (roadmap login sequence: invalid login -> error).
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate an employee and issue a JWT session token."""
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        # Burn the same bcrypt work as a real check (timing safe), then fail.
        verify_password(payload.password, _DUMMY_HASH)
        raise _INVALID_CREDENTIALS
    if (
        not user.is_active
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise _INVALID_CREDENTIALS
    token, expires_in = create_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserPublic.model_validate(user),
    )


@router.get("/me", response_model=UserPublic)
def read_current_user(
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    """Return the authenticated user; the role is derived from the session."""
    return UserPublic.model_validate(current_user)


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(
    current_user: User = Depends(get_current_user),
) -> TokenResponse:
    """Issue a fresh token for the authenticated user (short-lived sessions).

    Because ``get_current_user`` reloads the user from the database, a refresh
    also re-checks ``is_active`` — deactivated accounts cannot renew sessions.
    The client should call this before expiry instead of holding long-lived
    tokens.
    """
    token, expires_in = create_access_token(current_user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserPublic.model_validate(current_user),
    )