"""Request/response schemas for the API (T03)."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    """Credentials submitted to /auth/login."""

    email: str = Field(..., description="Employee email address")
    password: str = Field(..., min_length=1, description="Plaintext password")

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("must be a valid email address")
        return value

    @field_validator("password")
    @classmethod
    def _check_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes (bcrypt limit)")
        return value


class UserPublic(BaseModel):
    """User fields safe to expose to the client (never the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    is_admin: bool


class TokenResponse(BaseModel):
    """Bearer token issued by /auth/login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the token expires
    user: UserPublic