"""Authentication and account management.

Login is the one endpoint in the API that must work with no bearer token --
everything else requires one. User creation is admin-only: this platform does
not offer open self-registration, which is the wrong default for anything
that can eventually place trades.
"""

# No `from __future__ import annotations` in this file: slowapi's
# @limiter.limit decorator wraps the endpoint in a way that loses
# FastAPI's ability to resolve postponed (stringified) annotations,
# which silently turns the request body and every Depends() parameter
# into a required query parameter instead. Verified in isolation --
# this is the one exception to the codebase-wide convention.

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import SessionDep, SettingsDep
from app.auth.dependencies import CurrentUserDep, require_role
from app.auth.roles import Role
from app.auth.security import create_access_token, hash_password, verify_password
from app.core.logging import get_logger
from app.db.repositories import AuditRepository, UserRepository

log = get_logger(__name__)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserOut(BaseModel):
    username: str
    role: str


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.VIEWER


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(
    request: Request, body: LoginRequest, session: SessionDep, settings: SettingsDep
) -> TokenOut:
    """Exchange a username and password for an access token.

    The same generic error for "no such user" and "wrong password" -- telling
    the two apart would confirm which usernames exist to anyone probing.
    """
    users = UserRepository(session)
    user = users.get_by_username(body.username)

    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        AuditRepository(session).record(
            action="auth.login_failed",
            entity_type="user",
            entity_id=body.username,
            actor=body.username,
        )
        # Commit explicitly: the exception raised below would otherwise be
        # caught by session_scope()'s blanket rollback-on-exception, which
        # would discard the very audit record this failure is meant to leave
        # behind.
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password"
        )

    users.record_login(user)
    AuditRepository(session).record(
        action="auth.login", entity_type="user", entity_id=user.username, actor=user.username
    )
    token = create_access_token(settings, user.username, user.role)
    return TokenOut(access_token=token, role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUserDep) -> UserOut:
    return UserOut(username=user.username, role=user.role.value)


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN))],
)
def create_user(
    body: CreateUserRequest, session: SessionDep, admin: CurrentUserDep
) -> UserOut:
    users = UserRepository(session)
    if users.get_by_username(body.username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username is taken")

    user = users.create(body.username, hash_password(body.password), body.role.value)
    AuditRepository(session).record(
        action="auth.user_created",
        entity_type="user",
        entity_id=user.username,
        actor=admin.username,
        detail={"role": user.role},
    )
    session.flush()
    return UserOut(username=user.username, role=user.role)
