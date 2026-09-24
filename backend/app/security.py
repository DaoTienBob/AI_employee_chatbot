"""Password hashing and session tokens (T03 / FR01).

- Passwords: bcrypt with a per-user random salt (see requirements.txt).
- Sessions: signed JWT bearer tokens (PyJWT, HS256).
- The role claim inside the token is informational only. ``get_current_user``
  always reloads the user from SQLite, so the backend never trusts a role
  supplied by the frontend (roadmap security invariant).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models import User

_ALGORITHM = "HS256"

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt (random salt)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (constant time)."""
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database — treat as a failed login.
        return False


def create_access_token(user: User) -> tuple[str, int]:
    """Issue a signed session token; returns ``(token, expires_in_seconds)``."""
    expires_delta = timedelta(minutes=get_settings().access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, get_settings().secret_key, algorithm=_ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a session token; raises 401 on any failure."""
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise _credentials_error from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the ``Authorization: Bearer`` header.

    The user (and therefore role and admin permission) is reloaded from the
    database on every request; the token is only used to identify them.
    """
    if credentials is None or not credentials.credentials:
        raise _credentials_error
    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if subject is None:
        raise _credentials_error
    try:
        user_id = int(subject)
    except (ValueError, TypeError):
        raise _credentials_error
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_error
    return user