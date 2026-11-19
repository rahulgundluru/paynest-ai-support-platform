"""Import every model so Alembic autogenerate sees the full metadata."""

from app.models.audit import AuditLog
from app.models.identity import AuthSession, Region, RoleName, User, UserRegionScope, UserRole

__all__ = ["AuditLog", "AuthSession", "Region", "RoleName", "User", "UserRegionScope", "UserRole"]
