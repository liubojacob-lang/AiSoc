"""Knowledge domain: documents and vectorized chunks (RAG)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamped, UTCDateTime, UUIDPk, utcnow

JSONType = JSONB().with_variant(JSON(), "sqlite")

try:  # pgvector is PG-only; sqlite fallback stores raw bytes
    from pgvector.sqlalchemy import Vector

    EmbeddingType = Vector(1024).with_variant(LargeBinary, "sqlite")
except ImportError:  # pragma: no cover - pgvector ships as a hard dependency
    EmbeddingType = LargeBinary


class KnowledgeDocument(Base, UUIDPk, Timestamped):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("ix_docs_tenant_status", "tenant_id", "status"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False, default="text/markdown")
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class KnowledgeChunk(Base, UUIDPk):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("uq_chunks_doc_idx", "document_id", "chunk_index", unique=True),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False, default=0)
    embedding: Mapped[bytes | None] = mapped_column(EmbeddingType, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
