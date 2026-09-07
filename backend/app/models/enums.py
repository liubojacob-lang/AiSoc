"""All domain enumerations. Single source of truth; stored as VARCHAR(32)."""

from __future__ import annotations

from enum import StrEnum


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    NEW = "new"
    TRIAGING = "triaging"
    TRIAGED = "triaged"
    CONFIRMED_TRUE = "confirmed_true"
    INCIDENT_CREATED = "incident_created"
    CONFIRMED_FALSE = "confirmed_false"
    TRIAGE_FAILED = "triage_failed"


class HumanVerdict(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"


class TriageClassification(StrEnum):
    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    SUSPICIOUS = "suspicious"
    NEEDS_INVESTIGATION = "needs_investigation"


class IncidentStatus(StrEnum):
    NEW = "new"
    INVESTIGATING = "investigating"
    CONTAINED = "contained"
    ERADICATED = "eradicated"
    RECOVERED = "recovered"
    CLOSED = "closed"
    REOPENED = "reopened"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class RoleCode(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(StrEnum):
    """``resource:action`` strings enforced by backend dependencies."""

    ALERT_READ = "alert:read"
    ALERT_WRITE = "alert:write"  # confirm / close / escalate
    ALERT_INGEST = "alert:ingest"  # machine ingestion
    ALERT_TRIAGE = "alert:triage"  # trigger AI triage
    INCIDENT_READ = "incident:read"
    INCIDENT_WRITE = "incident:write"
    KB_READ = "kb:read"
    KB_WRITE = "kb:write"
    AI_RUN = "ai:run"  # chat / manual triage
    USER_MANAGE = "user:manage"
    SYSTEM_MANAGE = "system:manage"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[RoleCode, set[Permission]] = {
    RoleCode.ADMIN: set(Permission),
    RoleCode.ANALYST: {
        Permission.ALERT_READ,
        Permission.ALERT_WRITE,
        Permission.ALERT_TRIAGE,
        Permission.INCIDENT_READ,
        Permission.INCIDENT_WRITE,
        Permission.KB_READ,
        Permission.KB_WRITE,
        Permission.AI_RUN,
    },
    RoleCode.VIEWER: {
        Permission.ALERT_READ,
        Permission.INCIDENT_READ,
        Permission.KB_READ,
    },
}


# Explicit transition tables (docs/ARCHITECTURE.md §7). Illegal transitions
# raise business errors and get audit-logged.

ALERT_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.NEW: {AlertStatus.TRIAGING, AlertStatus.TRIAGE_FAILED},
    AlertStatus.TRIAGING: {AlertStatus.TRIAGED, AlertStatus.TRIAGE_FAILED},
    AlertStatus.TRIAGE_FAILED: {AlertStatus.TRIAGING},  # retry
    AlertStatus.TRIAGED: {
        AlertStatus.CONFIRMED_TRUE,
        AlertStatus.CONFIRMED_FALSE,
    },
    AlertStatus.CONFIRMED_TRUE: {AlertStatus.INCIDENT_CREATED},
    AlertStatus.INCIDENT_CREATED: set(),
    AlertStatus.CONFIRMED_FALSE: set(),
}

INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.NEW: {IncidentStatus.INVESTIGATING},
    IncidentStatus.INVESTIGATING: {IncidentStatus.CONTAINED, IncidentStatus.REOPENED},
    IncidentStatus.CONTAINED: {IncidentStatus.ERADICATED, IncidentStatus.INVESTIGATING},
    IncidentStatus.ERADICATED: {IncidentStatus.RECOVERED, IncidentStatus.INVESTIGATING},
    IncidentStatus.RECOVERED: {IncidentStatus.CLOSED, IncidentStatus.INVESTIGATING},
    IncidentStatus.CLOSED: {IncidentStatus.REOPENED},
    IncidentStatus.REOPENED: {IncidentStatus.INVESTIGATING, IncidentStatus.CLOSED},
}

TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.DONE: set(),
    TaskStatus.CANCELLED: set(),
}
