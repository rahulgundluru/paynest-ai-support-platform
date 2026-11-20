"""Import every model so Alembic autogenerate sees the full metadata."""

from app.models.approvals import Approval, ApprovalEvent, LearnedMemory
from app.models.audit import AuditLog
from app.models.evaluation import EvaluationResult, EvaluationRun, MonthlyCost
from app.models.identity import AuthSession, Region, RoleName, User, UserRegionScope, UserRole
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RetrievalLog,
    RetrievalResult,
    StatutoryRule,
)
from app.models.processing import Classification, Incident, IncidentLink, ModelUsage, RoutingDecision
from app.models.reference import Agent, Customer, FinanceSlaBreach, SlaTerm
from app.models.settings import SystemConfiguration
from app.models.tickets import (
    IngestionBatch,
    NormalizationLog,
    PiiDetection,
    PiiVaultEntry,
    SlaTracking,
    SourceRecord,
    Ticket,
    TicketEvent,
    TicketMessage,
)

__all__ = [
    "EvaluationResult",
    "EvaluationRun",
    "MonthlyCost",
    "SystemConfiguration",
    "Approval",
    "ApprovalEvent",
    "LearnedMemory",
    "Classification",
    "Incident",
    "IncidentLink",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeDocumentVersion",
    "ModelUsage",
    "RetrievalLog",
    "RetrievalResult",
    "RoutingDecision",
    "StatutoryRule",
    "Agent",
    "AuditLog",
    "AuthSession",
    "Customer",
    "FinanceSlaBreach",
    "IngestionBatch",
    "NormalizationLog",
    "PiiDetection",
    "PiiVaultEntry",
    "Region",
    "RoleName",
    "SlaTerm",
    "SlaTracking",
    "SourceRecord",
    "Ticket",
    "TicketEvent",
    "TicketMessage",
    "User",
    "UserRegionScope",
    "UserRole",
]
