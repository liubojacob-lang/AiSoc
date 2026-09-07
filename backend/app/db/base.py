"""Declarative base, shared mixins, and naming conventions.

UUIDv7 primary keys: time-ordered (index locality) and non-enumerable.
Python 3.13 stdlib lacks uuid7, so we generate per RFC 9562 here.
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Integer, MetaData
from sqlalchemy import DateTime as SATimeZone
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class UTCDateTime(TypeDecorator):
    """timezone-aware UTC timestamps on every backend.

    sqlite stores/reads naive datetimes; this guarantees tzinfo=UTC on read so
    comparisons with utcnow() never explode. PG timestamptz is unaffected.
    """

    impl = SATimeZone(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):  # noqa: D102
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= rand_a << 64
    value |= 0b10 << 62  # variant
    value |= rand_b
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class BigId:
    """Auto-increment big id for append-only log tables (audit, etc.)."""

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
