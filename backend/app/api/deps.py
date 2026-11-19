"""Request dependencies: DB session, authenticated principal, permission checks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rbac import Permission, permissions_for
from app.core.security import decode_token
from app.db.session import get_session
from app.models.identity import AuthSession, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: uuid.UUID
    permissions: frozenset[Permission]


_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


def _extract_token(request: Request, settings: Settings) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(settings.cookie_name)


async def get_principal(request: Request, session: SessionDep, settings: SettingsDep) -> Principal:
    token = _extract_token(request, settings)
    if not token:
        raise _UNAUTHORIZED
    try:
        claims = decode_token(token, settings.jwt_secret.get_secret_value())
    except jwt.PyJWTError:
        raise _UNAUTHORIZED from None
    auth_session = await session.get(AuthSession, claims.session_id)
    if (
        auth_session is None
        or auth_session.user_id != claims.user_id
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= datetime.now(tz=UTC)
    ):
        raise _UNAUTHORIZED
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return Principal(user=user, session_id=claims.session_id, permissions=permissions_for(user.role_names))


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require(permission: Permission) -> Callable[[Principal], Awaitable[Principal]]:
    async def checker(principal: PrincipalDep) -> Principal:
        if permission not in principal.permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission: {permission}")
        return principal

    return checker
