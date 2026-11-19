"""Authentication: credential check, session issue and revocation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_token, hash_password, verify_password
from app.models.identity import AuthSession, User
from app.services import audit

# Verifying against a fixed dummy hash keeps response time similar for unknown emails.
_DUMMY_HASH = hash_password("not-a-real-password-used-for-timing-only")


class AuthenticationError(Exception):
    pass


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise AuthenticationError
    return user


async def issue_session(session: AsyncSession, user: User, settings: Settings) -> tuple[str, datetime]:
    session_id = uuid.uuid4()
    token, expires_at = create_token(
        user.id, session_id, settings.jwt_secret.get_secret_value(), settings.jwt_ttl_minutes
    )
    session.add(AuthSession(id=session_id, user_id=user.id, expires_at=expires_at))
    user.last_login_at = datetime.now(tz=UTC)
    await audit.record(session, "auth.login", actor_user_id=user.id, entity_type="user", entity_id=str(user.id))
    await session.commit()
    return token, expires_at


async def revoke_session(session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(tz=UTC))
    )
    await audit.record(session, "auth.logout", actor_user_id=user_id, entity_type="user", entity_id=str(user_id))
    await session.commit()
