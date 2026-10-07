"""Identity HTTP routes: auth, users (admin), API keys (admin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Principal, require
from app.core.errors import Unauthenticated
from app.db.session import get_session
from app.models.enums import Permission
from app.models.identity import User
from app.modules.identity import schemas, service
from app.platform.audit import audit

router = APIRouter()

REFRESH_COOKIE = "aisoc_refresh"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=settings.is_prod,
        samesite="strict",
        max_age=settings.refresh_token_days * 24 * 3600,
        path=f"{settings.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth")


@router.post("/login", response_model=schemas.TokenPair)
async def login(
    body: schemas.LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    access, refresh_token = await service.login(session, body.email, body.password)
    _set_refresh_cookie(response, refresh_token)
    await audit(
        session,
        action="user.login",
        resource_type="user",
        detail={"email": body.email},
        request=request,
    )
    await session.commit()
    return schemas.TokenPair(access_token=access, expires_in=settings.access_token_minutes * 60)


@router.post("/refresh", response_model=schemas.TokenPair)
async def refresh(
    request: Request,
    response: Response,
    body: schemas.RefreshRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token and body is not None:
        token = body.refresh_token
    if not token:
        raise Unauthenticated("auth.refresh_missing", "no refresh token presented")
    access, new_refresh = await service.refresh(session, token)
    _set_refresh_cookie(response, new_refresh)
    return schemas.TokenPair(access_token=access, expires_in=settings.access_token_minutes * 60)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    body: schemas.RefreshRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    token = request.cookies.get(REFRESH_COOKIE) or (body.refresh_token if body else None)
    await service.logout(session, token)
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=schemas.UserOut)
async def me(
    principal: Principal = Depends(require(Permission.ALERT_READ)),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, principal.user_uuid)
    if user is None:
        from app.core.errors import NotFound

        raise NotFound("user", principal.user_uuid)
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=principal.roles,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


# ---------- users (admin) ----------


@router.get("/users", response_model=list[schemas.UserOut])
async def list_users(
    principal: Principal = Depends(require(Permission.USER_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    users = await service.list_users(session)
    out = []
    for u in users:
        roles = await service._roles_of(session, u.id)
        out.append(
            schemas.UserOut(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                is_active=u.is_active,
                roles=roles,
                last_login_at=u.last_login_at,
                created_at=u.created_at,
            )
        )
    return out


@router.post("/users", response_model=schemas.UserOut, status_code=201)
async def create_user(
    body: schemas.UserCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.USER_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    user = await service.create_user(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        roles=body.roles,
    )
    await audit(
        session,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        detail={"email": user.email, "roles": body.roles},
        actor_id=principal.user_uuid,
        request=request,
    )
    await session.commit()
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=body.roles,
        last_login_at=None,
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}", response_model=schemas.UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: schemas.UserUpdate,
    request: Request,
    principal: Principal = Depends(require(Permission.USER_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    user = await service.update_user(session, user_id, body.model_dump(exclude_unset=True))
    roles = await service._roles_of(session, user.id)
    await audit(
        session,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        detail={"fields": list(body.model_dump(exclude_unset=True))},
        actor_id=principal.user_uuid,
        request=request,
    )
    await session.commit()
    return schemas.UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=roles,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


# ---------- audit trail (admin) ----------

@router.get("/audit", response_model=list[dict])
async def list_audit(
    limit: int = 50,
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import select

    from app.models.ops import AuditLog

    rows = (
        await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "id": r.id, "actor_id": str(r.actor_id) if r.actor_id else None,
            "actor_type": r.actor_type, "action": r.action,
            "resource_type": r.resource_type, "resource_id": r.resource_id,
            "detail": r.detail, "ip": str(r.ip) if r.ip else None,
            "request_id": r.request_id, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------- api keys (admin) ----------


@router.get("/api-keys", response_model=list[schemas.ApiKeyOut])
async def list_api_keys(
    principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    return await service.list_api_keys(session)


@router.post("/api-keys", response_model=schemas.ApiKeyCreated, status_code=201)
async def create_api_key(
    body: schemas.ApiKeyCreate,
    request: Request,
    principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    row, plaintext = await service.create_api_key(
        session,
        name=body.name,
        scopes=body.scopes,
        rate_limit_per_min=body.rate_limit_per_min,
        expires_in_days=body.expires_in_days,
        created_by=principal.user_uuid,
    )
    await audit(
        session,
        action="api_key.create",
        resource_type="api_key",
        resource_id=row.id,
        detail={"name": row.name, "scopes": row.scopes},
        actor_id=principal.user_uuid,
        request=request,
    )
    await session.commit()
    return schemas.ApiKeyCreated(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=row.scopes,
        rate_limit_per_min=row.rate_limit_per_min,
        is_active=row.is_active,
        expires_at=row.expires_at,
        created_at=row.created_at,
        plaintext_key=plaintext,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require(Permission.SYSTEM_MANAGE)),
    session: AsyncSession = Depends(get_session),
):
    await service.revoke_api_key(session, key_id)
    await audit(
        session,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=key_id,
        actor_id=principal.user_uuid,
        request=request,
    )
    await session.commit()
