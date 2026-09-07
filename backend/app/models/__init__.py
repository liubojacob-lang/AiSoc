"""Aggregate model imports so Base.metadata sees every table."""

from app.models.ai import (
    AIConversation,
    AIMessage,
    AIRun,
    AIStep,
    AIToolCall,
    LLMCall,
)
from app.models.alerts import Alert, AlertEnrichment, AlertFeedback, TriageResult
from app.models.identity import (
    ApiKey,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.incidents import Comment, Incident, IncidentAlert, Task
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.ops import (
    Asset,
    AuditLog,
    IdempotencyKey,
    Notification,
    SystemConfig,
    ThreatIntel,
)

__all__ = [
    "Alert",
    "AlertEnrichment",
    "AlertFeedback",
    "TriageResult",
    "AIConversation",
    "AIMessage",
    "AIRun",
    "AIStep",
    "AIToolCall",
    "LLMCall",
    "ApiKey",
    "Permission",
    "RefreshToken",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "Comment",
    "Incident",
    "IncidentAlert",
    "Task",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Asset",
    "AuditLog",
    "IdempotencyKey",
    "Notification",
    "SystemConfig",
    "ThreatIntel",
]
