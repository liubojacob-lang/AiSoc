"""Identity service: login (with lockout), refresh rotation with reuse
detection, logout revocation, user management, API keys."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, Conflict, NotFound, Unauthenticated, ValidationFailed
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.db.base import utcnow
from app.models.enums import RoleCode
from app.models.identity import ApiKey, RefreshToken, Role, User, UserRole

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _access_expires_in() -> int:
    return settings.access_token_minutes * 60


async def _roles_of(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


async def _issue_tokens(session: AsyncSession, user: User) -> tuple[str, str, str]:
    roles = await _roles_of(session, user.id)
    access = create_access_token(str(user.id), roles)
    refresh, jti, family_id = create_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            jti=jti,
            family_id=family_id,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    return access, refresh, family_id


async def login(session: AsyncSession, email: str, password: str) -> tuple[str, str]:
    user = (
        await session.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()
    if user is None:
        # constant-ish time: still hash to avoid user enumeration by timing
        verify_password(password, hash_password("dummy-password-value"))
        raise Unauthenticated("auth.bad_credentials", "invalid email or password")
    if not user.is_active:
        raise Unauthenticated("auth.user_inactive", "account disabled")
    if user.locked_until and user.locked_until > utcnow():
        raise AppError("auth.locked", "account temporarily locked", status_code=423)

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
        await session.commit()
        raise Unauthenticated("auth.bad_credentials", "invalid email or password")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    access, refresh, _ = await _issue_tokens(session, user)
    await session.commit()
    return access, refresh


async def refresh(session: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """Rotate the refresh token. Reuse of an already-rotated token kills the
    whole family (theft signal)."""
    try:
        payload = decode_token(refresh_token, expected="refresh")
    except Exception as e:
        raise Unauthenticated("auth.invalid_refresh", "invalid refresh token") from e
    jti = payload["jti"]
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    ).scalar_one_or_none()
    if row is None or row.is_revoked:
        # reuse detection: revoke every token in this family
        if row is not None and row.revoked_at is not None:
            await session.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            await session.commit()
            raise Unauthenticated(
                "auth.refresh_reuse", "refresh token reuse detected; all sessions revoked"
            )
        raise Unauthenticated("auth.invalid_refresh", "refresh token expired or revoked")

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("auth.user_inactive", "user not found or inactive")

    row.revoked_at = utcnow()  # rotate out
    access, new_refresh, _ = await _issue_tokens(session, user)
    await session.commit()
    return access, new_refresh


async def logout(session: AsyncSession, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token, expected="refresh")
    except Exception:
        return  # logout is best-effort for garbage tokens
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.jti == payload["jti"], RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await session.commit()


# ---------- users (admin) ----------


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.execute(select(User).order_by(User.created_at))).scalars().all())


async def create_user(
    session: AsyncSession, *, email: str, password: str, display_name: str, roles: list[str]
) -> User:
    existing = (
        await session.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()
    if existing:
        raise Conflict("user.exists", "email already registered")
    for r in roles:
        if r not in [rc.value for rc in RoleCode]:
            raise ValidationFailed(f"unknown role: {r}", {"roles": roles})
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    for r in roles:
        role = (await session.execute(select(Role).where(Role.code == r))).scalar_one()
        session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    return user


async def update_user(session: AsyncSession, user_id: uuid.UUID, data: dict) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("user", user_id)
    if data.get("display_name") is not None:
        user.display_name = data["display_name"]
    if data.get("is_active") is not None:
        user.is_active = data["is_active"]
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
    if data.get("roles") is not None:
        for r in data["roles"]:
            if r not in [rc.value for rc in RoleCode]:
                raise ValidationFailed(f"unknown role: {r}", {"roles": data["roles"]})
        await session.execute(delete(UserRole).where(UserRole.user_id == user.id))
        for r in data["roles"]:
            role = (await session.execute(select(Role).where(Role.code == r))).scalar_one()
            session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.commit()
    return user


# ---------- api keys ----------


async def create_api_key(
    session: AsyncSession,
    *,
    name: str,
    scopes: list[str],
    rate_limit_per_min: int,
    expires_in_days: int | None,
    created_by: uuid.UUID,
) -> tuple[ApiKey, str]:
    plaintext, prefix, key_hash = generate_api_key()
    row = ApiKey(
        name=name,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        rate_limit_per_min=rate_limit_per_min,
        expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
        created_by=created_by,
    )
    session.add(row)
    await session.commit()
    return row, plaintext


async def list_api_keys(session: AsyncSession) -> list[ApiKey]:
    return list(
        (await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars().all()
    )


async def revoke_api_key(session: AsyncSession, key_id: uuid.UUID) -> None:
    row = await session.get(ApiKey, key_id)
    if row is None:
        raise NotFound("api_key", key_id)
    row.is_active = False
    await session.commit()
