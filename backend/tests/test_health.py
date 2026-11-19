from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]


async def test_health_is_dependency_free(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


async def test_ready_reports_database_migration_and_pgvector(client):
    response = await client.get("/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert checks["pgvector"] == "ok"
    head = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_current_head()
    assert checks["migration"] == head


async def test_unknown_route_uses_error_envelope(client):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


async def test_openapi_is_published(client):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/me", "/api/v1/audit-logs"} <= set(paths)
