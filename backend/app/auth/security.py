"""Password hashing and JWT issuance/verification.

Passwords are hashed with bcrypt (a work-factor hash, not a fast general-
purpose one, precisely so brute-forcing a stolen hash is expensive). Tokens
are signed, stateless JWTs -- verifying one requires no database round trip,
which is what keeps every protected route's auth check cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import Settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # A malformed stored hash is a data problem, not a matching password.
        return False


@dataclass(frozen=True)
class TokenPayload:
    subject: str
    role: str
    issued_at: datetime
    expires_at: datetime


class InvalidToken(ValueError):
    """A token failed to verify: expired, malformed, or wrongly signed."""


def create_access_token(settings: Settings, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_expiry_minutes)
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("token is invalid") from exc

    try:
        return TokenPayload(
            subject=payload["sub"],
            role=payload["role"],
            issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except KeyError as exc:
        raise InvalidToken(f"token is missing required claim: {exc}") from exc
