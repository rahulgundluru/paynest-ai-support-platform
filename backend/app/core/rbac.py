"""Role → permission mapping, defined in code and reviewed like any other business rule.

Every permission listed here is enforced by at least one endpoint. Later phases add permissions
together with the endpoints that need them (approvals, PII reveal, evaluations, settings).
"""

from __future__ import annotations

import enum

from app.models.identity import RoleName


class Permission(enum.StrEnum):
    AUDIT_READ = "audit:read"
    USERS_MANAGE = "users:manage"
    TICKETS_READ = "tickets:read"
    CUSTOMERS_READ = "customers:read"
    SLA_READ = "sla:read"
    INGESTION_RUN = "ingestion:run"
    INGESTION_READ = "ingestion:read"
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    INCIDENTS_MANAGE = "incidents:manage"
    TICKETS_PROCESS = "tickets:process"
    APPROVALS_READ = "approvals:read"
    APPROVALS_EDIT = "approvals:edit"
    APPROVALS_DECIDE = "approvals:decide"
    PII_REVEAL = "pii:reveal"
    SETTINGS_READ = "settings:read"
    SETTINGS_MANAGE = "settings:manage"


_SUPPORT = frozenset(
    {
        Permission.TICKETS_READ,
        Permission.CUSTOMERS_READ,
        Permission.KNOWLEDGE_READ,
        Permission.APPROVALS_READ,
        Permission.APPROVALS_EDIT,
    }
)

ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.AGENT_L1: _SUPPORT,
    RoleName.AGENT_L2: _SUPPORT | {Permission.TICKETS_PROCESS, Permission.APPROVALS_DECIDE},
    RoleName.ENGINEER_L3: _SUPPORT,
    RoleName.SUPPORT_LEAD: _SUPPORT
    | {
        Permission.AUDIT_READ,
        Permission.SLA_READ,
        Permission.INGESTION_RUN,
        Permission.INGESTION_READ,
        Permission.INCIDENTS_MANAGE,
        Permission.TICKETS_PROCESS,
        Permission.APPROVALS_DECIDE,
        Permission.SETTINGS_READ,
    },
    RoleName.KB_OWNER: frozenset({Permission.TICKETS_READ, Permission.KNOWLEDGE_READ, Permission.KNOWLEDGE_MANAGE}),
    RoleName.DPO: frozenset(
        {Permission.AUDIT_READ, Permission.TICKETS_READ, Permission.INGESTION_READ, Permission.PII_REVEAL}
    ),
    RoleName.FINANCE_VIEWER: frozenset({Permission.CUSTOMERS_READ, Permission.SLA_READ}),
    # Admin gets everything except reading original personal data, which is the DPO's alone.
    RoleName.ADMIN: frozenset(Permission) - {Permission.PII_REVEAL},
}


def permissions_for(roles: list[RoleName]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)
