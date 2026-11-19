from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import PrincipalDep, SessionDep, SettingsDep
from app.core.ratelimit import login_limiter
from app.core.rbac import permissions_for
from app.models.identity import User
from app.schemas.auth import LoginRequest, LoginResponse, UserOut
from app.services import audit
from app.services.auth import AuthenticationError, authenticate, issue_session, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=user.role_names,
        regions=user.regions,
        permissions=sorted(permissions_for(user.role_names)),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> LoginResponse:
    client = request.client.host if request.client else "unknown"
    retry_after = login_limiter.hit(f"{body.email}|{client}")
    if retry_after is not None:
        await audit.record(session, "auth.rate_limited", details={"retry_after_s": round(retry_after)})
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(max(1, round(retry_after)))},
        )
    try:
        user = await authenticate(session, body.email, body.password)
    except AuthenticationError:
        await audit.record(session, "auth.login_failed", details={"reason": "invalid_credentials"})
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password") from None
    token, expires_at = await issue_session(session, user, settings)
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_ttl_minutes * 60,
        path="/",
    )
    return LoginResponse(access_token=token, expires_at=expires_at, user=_user_out(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: PrincipalDep, response: Response, session: SessionDep, settings: SettingsDep) -> Response:
    await revoke_session(session, principal.user.id, principal.session_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(settings.cookie_name, path="/")
    return response


@router.get("/me", response_model=UserOut)
async def me(principal: PrincipalDep) -> UserOut:
    return _user_out(principal.user)
