"""Identity module: request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 vocabulary, not a secret
    expires_in: int  # access token TTL in seconds


class RefreshRequest(BaseModel):
    # sent via httpOnly cookie in the browser flow; body fallback for API clients
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    is_active: bool
    roles: list[str] = []
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    roles: list[str] = Field(default_factory=lambda: ["analyst"])


class UserUpdate(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=lambda: ["alerts:write"])
    rate_limit_per_min: int = Field(default=600, ge=1, le=10000)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit_per_min: int
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    plaintext_key: str  # shown exactly once
