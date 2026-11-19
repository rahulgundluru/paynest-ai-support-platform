"""Role → permission mapping, defined in code and reviewed like any other business rule.

Later phases add permissions here (e.g. ticket processing, approvals, PII reveal) together
with the endpoints that need them, so every permission in this file is enforced somewhere.
"""

from __future__ import annotations

import enum

from app.models.identity import RoleName


class Permission(enum.StrEnum):
    AUDIT_READ = "audit:read"
    USERS_MANAGE = "users:manage"


ROLE_PERMISSIONS: dict[RoleName, frozenset[Permission]] = {
    RoleName.AGENT_L1: frozenset(),
    RoleName.AGENT_L2: frozenset(),
    RoleName.ENGINEER_L3: frozenset(),
    RoleName.SUPPORT_LEAD: frozenset({Permission.AUDIT_READ}),
    RoleName.KB_OWNER: frozenset(),
    RoleName.DPO: frozenset({Permission.AUDIT_READ}),
    RoleName.FINANCE_VIEWER: frozenset(),
    RoleName.ADMIN: frozenset({Permission.AUDIT_READ, Permission.USERS_MANAGE}),
}


def permissions_for(roles: list[RoleName]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)
