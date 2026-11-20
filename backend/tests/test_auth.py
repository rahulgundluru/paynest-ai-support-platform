import logging

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import get_sessionmaker
from app.models.audit import AuditLog
from app.models.identity import Region, RoleName


async def _login(client, email, password):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_returns_token_cookie_and_profile(client, make_user):
    _, password = await make_user(roles=(RoleName.SUPPORT_LEAD,), regions=(Region.IN, Region.UAE))
    response = await _login(client, "LEAD@example.test", password)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["roles"] == ["support_lead"]
    assert body["user"]["regions"] == ["IN", "UAE"]
    assert "audit:read" in body["user"]["permissions"] and "users:manage" not in body["user"]["permissions"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


async def test_wrong_password_is_rejected_and_audited(client, make_user):
    await make_user()
    response = await _login(client, "lead@example.test", "definitely-wrong-password")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"
    async with get_sessionmaker()() as session:
        actions = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.login_failed" in actions


async def test_unknown_user_gets_same_error(client):
    response = await _login(client, "nobody@example.test", "whatever-password")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


async def test_inactive_user_cannot_log_in(client, make_user):
    _, password = await make_user(active=False)
    assert (await _login(client, "lead@example.test", password)).status_code == 401


async def test_me_accepts_bearer_and_cookie(client, make_user):
    _, password = await make_user()
    token = (await _login(client, "lead@example.test", password)).json()["access_token"]
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 200
    # the client's cookie jar now holds the session cookie from login
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_logout_revokes_the_session(client, make_user):
    _, password = await make_user()
    token = (await _login(client, "lead@example.test", password)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_tampered_or_missing_token_is_rejected(client, make_user):
    _, password = await make_user()
    token = (await _login(client, "lead@example.test", password)).json()["access_token"]
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})).status_code == 401


async def test_deactivated_user_loses_access_immediately(client, make_user):
    user, password = await make_user()
    token = (await _login(client, "lead@example.test", password)).json()["access_token"]
    async with get_sessionmaker()() as session:
        await session.execute(text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user.id})
        await session.commit()
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_rbac_blocks_audit_log_for_l1_and_allows_lead(client, make_user):
    _, l1_pw = await make_user(email="l1@example.test", roles=(RoleName.AGENT_L1,))
    _, lead_pw = await make_user(email="lead@example.test", roles=(RoleName.SUPPORT_LEAD,))
    l1 = (await _login(client, "l1@example.test", l1_pw)).json()["access_token"]
    lead = (await _login(client, "lead@example.test", lead_pw)).json()["access_token"]
    client.cookies.clear()
    denied = await client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {l1}"})
    assert denied.status_code == 403
    allowed = await client.get("/api/v1/audit-logs?action=auth.login", headers={"Authorization": f"Bearer {lead}"})
    assert allowed.status_code == 200
    page = allowed.json()
    assert page["total"] == 2
    assert {item["action"] for item in page["items"]} == {"auth.login"}


async def test_audit_log_is_append_only():
    async with get_sessionmaker()() as session:
        session.add(AuditLog(action="test.event"))
        await session.commit()
    for statement in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"):
        async with get_sessionmaker()() as session:
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(text(statement))


async def test_request_logs_never_contain_submitted_secrets(client, make_user, caplog):
    await make_user()
    secret = "Sup3r-Secret-Value-Do-Not-Log"
    with caplog.at_level(logging.INFO):
        await _login(client, "lead@example.test", secret)
        await client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": secret})
    formatted = "\n".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert secret not in formatted
