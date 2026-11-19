"""Integration-test fixtures. Tests run against a real PostgreSQL + pgvector database.

Set TEST_DATABASE_URL (postgresql+asyncpg://...) to a disposable database; it is migrated
to head once per session and truncated between tests.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")
if not TEST_DB:
    pytest.exit("TEST_DATABASE_URL is not set; tests need a disposable PostgreSQL + pgvector database", returncode=2)

os.environ["DATABASE_URL"] = TEST_DB
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["COOKIE_SECURE"] = "false"
os.environ["LOG_LEVEL"] = "INFO"

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.identity import Region, RoleName, User, UserRegionScope, UserRole  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, env=os.environ)


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with get_sessionmaker()() as session:
        # TRUNCATE does not fire the row-level append-only trigger on audit_logs.
        await session.execute(text("TRUNCATE audit_logs, auth_sessions, user_region_scopes, user_roles, users CASCADE"))
        await session.commit()


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


UserFactory = Callable[..., Awaitable[tuple[User, str]]]


@pytest.fixture
def make_user() -> UserFactory:
    async def _make(
        email: str = "lead@example.test",
        roles: tuple[RoleName, ...] = (RoleName.SUPPORT_LEAD,),
        regions: tuple[Region, ...] = (Region.IN,),
        active: bool = True,
    ) -> tuple[User, str]:
        password = secrets.token_urlsafe(18)
        async with get_sessionmaker()() as session:
            user = User(email=email, full_name="Test User", password_hash=hash_password(password), is_active=active)
            user.roles = [UserRole(role=r) for r in roles]
            user.region_scopes = [UserRegionScope(region=r) for r in regions]
            session.add(user)
            await session.commit()
            return user, password

    return _make
