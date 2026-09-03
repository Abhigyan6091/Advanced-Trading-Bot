"""FastAPI auth dependencies.

``require_authenticated`` verifies the bearer token and loads the user;
``require_role`` builds on it to additionally check RBAC. Applied at the
router level (``APIRouter(dependencies=[...])``) so protecting a whole
section of the API is a one-line change, not a per-endpoint one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.roles import Role, satisfies
from app.auth.security import InvalidToken, decode_access_token
from app.core.config import Settings, get_settings
from app.db.repositories import UserRepository
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: Role


def _db_session() -> Session:
    yield from get_db()


def require_authenticated(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(_db_session)],
) -> CurrentUser:
    """Verify the bearer token and confirm the account is still active.

    Checking the account against the database, not just the token's
    signature, is what makes deactivating a user actually take effect before
    their existing tokens expire.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(settings, credentials.credentials)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = UserRepository(session).get_by_username(payload.subject)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account is no longer active",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(username=user.username, role=Role(user.role))


CurrentUserDep = Annotated[CurrentUser, Depends(require_authenticated)]


def require_role(minimum: Role):
    """Build a dependency requiring at least ``minimum`` role.

    Usage: ``dependencies=[Depends(require_role(Role.ADMIN))]`` on a router
    or route, layered on top of (not instead of) require_authenticated.
    """

    def _check(user: CurrentUserDep) -> CurrentUser:
        if not satisfies(user.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires the {minimum.value} role or higher",
            )
        return user

    return _check
