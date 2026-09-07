"""Idempotent seed: permissions, system roles, bootstrap admin.

Runs on startup (dev/test) and via `python -m app.db.seed` (prod deploy step).
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import DEFAULT_TENANT_ID
from app.db.session import get_sessionmaker
from app.models.enums import ROLE_PERMISSIONS, RoleCode
from app.models.enums import Permission as PermissionEnum
from app.models.identity import Permission as PermissionModel
from app.models.identity import Role, RolePermission, User, UserRole

ADMIN_EMAIL = "admin@aisoc.dev"


async def seed(session: AsyncSession) -> None:
    # permissions
    existing = (await session.execute(select(PermissionModel.code))).scalars().all()
    for perm in PermissionEnum:
        if perm not in existing:
            session.add(PermissionModel(code=perm, description=perm))

    # roles + role_permissions
    for code, perms in ROLE_PERMISSIONS.items():
        role = (await session.execute(select(Role).where(Role.code == code))).scalar_one_or_none()
        if role is None:
            role = Role(
                tenant_id=DEFAULT_TENANT_ID,
                code=code,
                name=code.capitalize(),
                is_system=True,
            )
            session.add(role)
            await session.flush()
        perm_ids = (
            (
                await session.execute(
                    select(PermissionModel.id).where(PermissionModel.code.in_(perms))
                )
            )
            .scalars()
            .all()
        )
        existing_rp = (
            (
                await session.execute(
                    select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
                )
            )
            .scalars()
            .all()
        )
        for pid in perm_ids:
            if pid not in existing_rp:
                session.add(RolePermission(role_id=role.id, permission_id=pid))

    # bootstrap admin (idempotent by email)
    admin = (
        await session.execute(select(User).where(User.email == ADMIN_EMAIL))
    ).scalar_one_or_none()
    if admin is None:
        password = settings.bootstrap_admin_password or uuid.uuid4().hex[:16]
        admin = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=ADMIN_EMAIL,
            password_hash=hash_password(password),
            display_name="Administrator",
        )
        session.add(admin)
        await session.flush()
        admin_role = (
            await session.execute(select(Role).where(Role.code == RoleCode.ADMIN))
        ).scalar_one()
        session.add(UserRole(user_id=admin.id, role_id=admin_role.id))
        await session.commit()
        # only print when we generated one; never log existing secrets
        print(f"[seed] bootstrap admin created: {ADMIN_EMAIL} / temporary password: {password}")
        if not settings.bootstrap_admin_password and settings.is_prod:
            print("[seed] WARNING: set BOOTSTRAP_ADMIN_PASSWORD env in prod and rotate this!")
    else:
        await session.commit()


async def main() -> None:
    maker = get_sessionmaker()
    async with maker() as s:
        await seed(s)


if __name__ == "__main__":
    asyncio.run(main())
