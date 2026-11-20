from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.core.rbac import Permission
from app.models.identity import Region, RoleName

# Syntactic check only. Strict validators (email-validator) reject reserved domains such as
# ".test"/".internal" that staff and local test accounts legitimately use.
LoginEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
]


class LoginRequest(BaseModel):
    email: LoginEmail
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    roles: list[RoleName]
    regions: list[Region]
    permissions: list[Permission]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    expires_at: datetime
    user: UserOut
