"""Users, roles, region scopes and login sessions.

Permissions are defined in code (app.core.rbac) against these role names, so a role
cannot silently gain a permission through a database edit.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoleName(enum.StrEnum):
    AGENT_L1 = "agent_l1"
    AGENT_L2 = "agent_l2"
    ENGINEER_L3 = "engineer_l3"
    SUPPORT_LEAD = "support_lead"
    KB_OWNER = "kb_owner"
    DPO = "dpo"
    FINANCE_VIEWER = "finance_viewer"
    ADMIN = "admin"


class Region(enum.StrEnum):
    IN = "IN"
    UAE = "UAE"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    region_scopes: Mapped[list[UserRegionScope]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    @property
    def role_names(self) -> list[RoleName]:
        return sorted(r.role for r in self.roles)

    @property
    def regions(self) -> list[Region]:
        return sorted(r.region for r in self.region_scopes)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[RoleName] = mapped_column(
        Enum(RoleName, name="role_name", values_callable=lambda e: [m.value for m in e]), primary_key=True
    )
    user: Mapped[User] = relationship(back_populates="roles")


class UserRegionScope(Base):
    __tablename__ = "user_region_scopes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    region: Mapped[Region] = mapped_column(
        Enum(Region, name="region_code", values_callable=lambda e: [m.value for m in e]), primary_key=True
    )
    user: Mapped[User] = relationship(back_populates="region_scopes")


class AuthSession(Base):
    """Server-side record of an issued token, so logout and deactivation revoke it immediately."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
