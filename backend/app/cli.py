"""Administrative CLI.

  python -m app.cli create-user --email a@b.c --name "A B" --role admin --region IN --region UAE

The password is read from the PAYNEST_NEW_USER_PASSWORD environment variable, or prompted
for interactively, so it never appears in shell history or process listings.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_engine, get_sessionmaker
from app.models.identity import Region, RoleName, User, UserRegionScope, UserRole
from app.services import audit


async def create_user(email: str, name: str, roles: list[RoleName], regions: list[Region], password: str) -> None:
    async with get_sessionmaker()() as session:
        email = email.strip().lower()
        if await session.scalar(select(User).where(User.email == email)):
            raise SystemExit(f"user already exists: {email}")
        user = User(email=email, full_name=name, password_hash=hash_password(password))
        user.roles = [UserRole(role=r) for r in roles]
        user.region_scopes = [UserRegionScope(region=r) for r in regions]
        session.add(user)
        await session.flush()
        await audit.record(
            session,
            "user.created",
            entity_type="user",
            entity_id=str(user.id),
            details={"roles": [r.value for r in roles], "regions": [r.value for r in regions], "via": "cli"},
        )
        await session.commit()
        print(f"created user {email} ({user.id})")
    await get_engine().dispose()


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", action="append", required=True, choices=[r.value for r in RoleName])
    cu.add_argument("--region", action="append", required=True, choices=[r.value for r in Region])
    args = parser.parse_args()

    password = os.environ.get("PAYNEST_NEW_USER_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 12:
        print("password must be at least 12 characters", file=sys.stderr)
        return 2
    asyncio.run(
        create_user(args.email, args.name, [RoleName(r) for r in args.role], [Region(r) for r in args.region], password)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
