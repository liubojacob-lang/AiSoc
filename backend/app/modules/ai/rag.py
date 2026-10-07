"""RAG primitives: markdown-aware chunking, embedding via gateway, and
retrieval over knowledge_chunks.

Two retrieval backends behind one interface:
- PostgreSQL: pgvector HNSW ``<=>`` (cosine distance)
- SQLite (dev/test): brute-force cosine in Python over stored float blobs

Chunk size follows docs/DATABASE.md: 800 tokens (~3200 chars), 15% overlap,
markdown headings kept in chunk metadata so citations can jump to context.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import DEFAULT_TENANT_ID
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.modules.ai.gateway import LLMGateway

TOKEN_CHARS = 4  # crude but consistent token estimate
CHUNK_TOKENS = 800
OVERLAP = 0.15


@dataclass
class Chunk:
    content: str
    meta: dict


def split_into_chunks(content: str, title: str = "") -> list[Chunk]:
    """Markdown-aware splitter: split on headings when possible, then pack to
    ~CHUNK_TOKENS with tail overlap so cross-boundary context survives."""
    sections = re.split(r"(?m)^(#{1,6} .*$)", content)
    pieces: list[tuple[str, str]] = []  # (heading_path, body)
    heading = title or ""
    if sections[0].strip():
        pieces.append((heading, sections[0]))
    for i in range(1, len(sections), 2):
        heading = sections[i].lstrip("#").strip()
        pieces.append((heading, sections[i + 1]))

    max_chars = CHUNK_TOKENS * TOKEN_CHARS
    overlap_chars = int(max_chars * OVERLAP)
    chunks: list[Chunk] = []
    for heading, body in pieces:
        body = body.strip()
        if not body:
            continue
        if len(body) <= max_chars:
            chunks.append(Chunk(f"{heading}\n\n{body}".strip(), {"heading": heading}))
            continue
        start = 0
        while start < len(body):
            end = min(start + max_chars, len(body))
            # prefer breaking at paragraph boundary
            nl = body.rfind("\n\n", start + max_chars - 200, end)
            if nl != -1 and nl > start:
                end = nl
            piece = body[start:end].strip()
            if piece:
                chunks.append(Chunk(f"{heading}\n\n{piece}".strip(), {"heading": heading}))
            if end >= len(body):
                break
            start = max(end - overlap_chars, start + 1)
    return chunks


def vector_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_vector(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def embed_texts(gateway: LLMGateway, texts: list[str]) -> list[list[float]]:
    return await gateway.embed(texts)


async def index_document(
    session: AsyncSession,
    gateway: LLMGateway,
    *,
    document_id,
    title: str,
    content: str,
) -> int:
    """Chunk + embed + persist. Caller owns commit."""
    chunks = split_into_chunks(content, title=title)
    if not chunks:
        return 0
    vectors = await gateway.embed([c.content for c in chunks])
    for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(
            KnowledgeChunk(
                document_id=document_id,
                chunk_index=i,
                content=chunk.content,
                token_count=max(1, len(chunk.content) // TOKEN_CHARS),
                meta=chunk.meta,
                embedding=_prepare_embedding(session, vec),
            )
        )
    return len(chunks)


def _is_sqlite(session: AsyncSession) -> bool:
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncEngine

    return cast(AsyncEngine, session.bind).dialect.name == "sqlite"


def _prepare_embedding(session: AsyncSession, vec: list[float]):
    """pgvector accepts python lists on PG; sqlite variant stores a blob."""
    if _is_sqlite(session):
        return vector_to_blob(vec)
    return vec


async def retrieve(
    session: AsyncSession,
    gateway: LLMGateway,
    *,
    query: str,
    k: int = 6,
    min_score: float = 0.3,
    tenant_id=DEFAULT_TENANT_ID,
) -> list[dict]:
    """Return [{content, score, document_id, meta}] ranked by cosine similarity.

    PostgreSQL uses the ANN index path (pgvector cosine_distance); other
    dialects (sqlite dev/test) use a portable brute-force scan. Both branches
    filter out soft-deleted / non-indexed documents.
    """
    [qvec] = await gateway.embed([query])

    if not _is_sqlite(session):
        distance = KnowledgeChunk.embedding.cosine_distance(qvec)
        stmt = (
            select(KnowledgeChunk, (1 - distance).label("score"))
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeDocument.deleted_at.is_(None),
                KnowledgeDocument.status == "indexed",
            )
            .order_by(distance)
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        return [
            {
                "content": chunk.content,
                "score": round(float(score), 4),
                "document_id": str(chunk.document_id),
                "meta": chunk.meta or {},
            }
            for chunk, score in rows
            if score is not None and score >= min_score
        ]

    # portable brute-force path (sqlite dev/test)
    stmt = (
        select(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status == "indexed",
        )
    )
    chunks = (await session.execute(stmt)).scalars().all()
    scored: list[dict[str, Any]] = []
    for c in chunks:
        emb = c.embedding
        if emb is None:
            continue
        vec = blob_to_vector(emb) if isinstance(emb, (bytes, bytearray)) else list(emb)
        score = cosine(qvec, vec)
        if score >= min_score:
            scored.append(
                {
                    "content": c.content,
                    "score": round(score, 4),
                    "document_id": str(c.document_id),
                    "meta": c.meta or {},
                }
            )
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]
