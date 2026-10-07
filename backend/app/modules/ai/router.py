"""AI assistant HTTP routes: copilot chat + conversation history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, require
from app.db.session import get_session
from app.models.ai import AIConversation, AIMessage
from app.models.enums import Permission
from app.modules.ai.copilot import CopilotService
from app.modules.ai.gateway import get_gateway

router = APIRouter()


class ChatTurnRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class Citation(BaseModel):
    kind: str
    title: str
    detail: str


class ChatTurnResponse(BaseModel):
    conversation_id: uuid.UUID
    answer: str
    refs: list[Citation]
    model_key: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: str


class MessageOut(BaseModel):
    role: str
    content: str
    refs: list[Citation] | None
    created_at: str


@router.post("/chat", response_model=ChatTurnResponse)
async def chat(
    body: ChatTurnRequest,
    principal: Principal = Depends(require(Permission.AI_RUN)),
    session: AsyncSession = Depends(get_session),
):
    service = CopilotService(get_gateway(), session, tenant_id=principal.tenant_id)
    result = await service.ask(
        user_id=principal.user_uuid,
        question=body.question,
        conversation_id=body.conversation_id,
    )
    return ChatTurnResponse(
        conversation_id=result["conversation_id"],
        answer=result["answer"],
        refs=[Citation(**r) for r in result["refs"]],
        model_key=result["model_key"],
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    principal: Principal = Depends(require(Permission.AI_RUN)),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(AIConversation)
            .where(
                AIConversation.user_id == principal.user_uuid,
                AIConversation.user_id == principal.user_uuid,
            )
            .order_by(AIConversation.updated_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return [
        ConversationOut(id=c.id, title=c.title, created_at=c.created_at.isoformat())
        for c in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require(Permission.AI_RUN)),
    session: AsyncSession = Depends(get_session),
):
    conv = await session.get(AIConversation, conversation_id)
    if conv is None or conv.user_id != principal.user_uuid:
        from app.core.errors import NotFound

        raise NotFound("conversation", conversation_id)
    rows = (
        await session.execute(
            select(AIMessage)
            .where(
                AIMessage.conversation_id == conversation_id,
                AIMessage.role.in_(["user", "assistant"]),  # tool messages are internal detail
            )
            .order_by(AIMessage.created_at)
        )
    ).scalars().all()
    return [
        MessageOut(
            role=m.role,
            content=m.content,
            refs=[Citation(**r) for r in (m.refs or [])] or None,
            created_at=m.created_at.isoformat(),
        )
        for m in rows
    ]
