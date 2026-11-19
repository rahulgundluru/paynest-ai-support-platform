"""Administrative CLI.

  python -m app.cli create-user --email a@b.c --name "A B" --role admin --region IN --region UAE

The password is read from the PAYNEST_NEW_USER_PASSWORD environment variable, or prompted
for interactively, so it never appears in shell history or process listings.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_engine, get_sessionmaker
from app.models.identity import Region, RoleName, User, UserRegionScope, UserRole
from app.services import audit
from app.services.ingestion.pipeline import SourceDataMissing, run_ingestion


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


async def ingest(path: Path) -> int:
    settings = get_settings()
    async with get_sessionmaker()() as session:
        try:
            batch = await run_ingestion(session, path, retention_days=settings.pii_retention_days)
        except SourceDataMissing as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"batch_id": str(batch.id), "status": batch.status, **batch.summary}, indent=2))
    await get_engine().dispose()
    return 0 if batch.status == "completed" else 1


async def pipeline_step(command: str, source_dir: Path) -> int:
    from app.services.deduplication.service import run_detection
    from app.services.knowledge.ingest import index_knowledge
    from app.services.routing.service import route_all

    async with get_sessionmaker()() as session:
        if command == "index-knowledge":
            result = await index_knowledge(session, source_dir)
        elif command == "detect-duplicates":
            result = await run_detection(session)
        else:
            result = await route_all(session)
        print(json.dumps(result, indent=2, default=str))
    await get_engine().dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", action="append", required=True, choices=[r.value for r in RoleName])
    cu.add_argument("--region", action="append", required=True, choices=[r.value for r in Region])
    ing = sub.add_parser("ingest", help="ingest the source exports (idempotent) and print the batch summary")
    ing.add_argument("--source-dir", default=None, help="defaults to DATA_SOURCE_DIR")
    sub.add_parser("index-knowledge", help="build/refresh the knowledge base from the source mirror")
    sub.add_parser("detect-duplicates", help="rebuild automatic resubmission and incident groupings")
    sub.add_parser("route-all", help="record a routing decision for every ticket (baseline)")
    args = parser.parse_args()

    if args.command == "ingest":
        return asyncio.run(ingest(Path(args.source_dir or get_settings().data_source_dir).resolve()))
    if args.command in ("index-knowledge", "detect-duplicates", "route-all"):
        return asyncio.run(pipeline_step(args.command, Path(get_settings().data_source_dir).resolve()))

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
