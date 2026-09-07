"""Request authentication & authorization dependencies.

Two principal kinds:
- User principals (JWT access token in Authorization header)
- Machine principals (API key in X-API-Key header, scoped, for ingestion)

Authorization is enforced *here on the backend* via ``require(...)``
dependencies. Frontend permission checks are UX only, never a boundary.
Role→permission resolution uses the seeded system roles (ROLE_PERMISSIONS
map); custom roles are a P2 extension that would swap this for a DB lookup.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import jwt as pyjwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDenied, Unauthenticated
from app.core.security import decode_token, hash_api_key
from app.db.base import utcnow
from app.db.session import get_session
from app.models.enums import ROLE_PERMISSIONS, Permission, RoleCode
from app.models.identity import ApiKey, Role, User, UserRole

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    kind: str  # "user" | "api_key"
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None = None
    email: str | None = None
    display_name: str = ""
    roles: list[str] = field(default_factory=list)
    permissions: set[Permission] = field(default_factory=set)
    api_key_id: uuid.UUID | None = None
    scopes: set[str] = field(default_factory=set)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


async def _load_user_principal(session: AsyncSession, token: str) -> Principal:
    try:
        payload = decode_token(token, expected="access")
    except pyjwt.PyJWTError as e:
        raise Unauthenticated(
            "auth.invalid_token", f"invalid access token: {e.__class__.__name__}"
        ) from e
    user_id = payload.get("sub")
    if not user_id:
        raise Unauthenticated("auth.invalid_token", "token missing subject")
    user = await session.get(User, uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise Unauthenticated("auth.user_inactive", "user not found or inactive")
    role_codes = (
        (
            await session.execute(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    perms: set[Permission] = set()
    for code in role_codes:
        perms |= ROLE_PERMISSIONS.get(RoleCode(code), set())
    return Principal(
        kind="user",
        tenant_id=user.tenant_id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=list(role_codes),
        permissions=perms,
    )


async def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """User principal via Bearer token. API keys are only accepted on the
    dedicated ingest dependency, never here."""
    if credentials is None:
        raise Unauthenticated()
    return await _load_user_principal(session, credentials.credentials)


async def get_api_key_principal(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Principal:
    raw = request.headers.get("X-API-Key", "")
    if not raw:
        raise Unauthenticated("auth.api_key_required", "X-API-Key header required")
    row = (
        await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw)))
    ).scalar_one_or_none()
    if row is None or not row.is_active:
        raise Unauthenticated("auth.invalid_api_key", "unknown or inactive API key")
    if row.expires_at is not None and row.expires_at <= utcnow():
        raise Unauthenticated("auth.api_key_expired", "API key expired")
    return Principal(
        kind="api_key",
        tenant_id=row.tenant_id,
        api_key_id=row.id,
        permissions={Permission.ALERT_INGEST},
        scopes=set(row.scopes),
    )


def require(*needed: Permission):
    """Dependency factory: authorize a route behind one or more permissions."""

    async def _checker(principal: Principal = Depends(get_principal)) -> Principal:
        for p in needed:
            if not principal.has(p):
                raise PermissionDenied(p)
        return principal

    return _checker


def require_scope(scope: str):
    async def _checker(principal: Principal = Depends(get_api_key_principal)) -> Principal:
        if scope not in principal.scopes:
            raise PermissionDenied(scope)
        return principal

    return _checker
