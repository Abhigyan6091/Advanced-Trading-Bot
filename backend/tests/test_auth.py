"""Password hashing, JWT issuance, and the FastAPI auth dependencies."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.auth.roles import Role, satisfies
from app.auth.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.config import Settings


def settings(**overrides) -> Settings:
    base = dict(
        postgres_user="u", postgres_password="p", postgres_db="d",
        postgres_host="h", postgres_port=5432, jwt_secret="test-secret",
    )
    return Settings(**{**base, **overrides})


class TestPasswordHashing:
    def test_a_correct_password_verifies(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed)

    def test_a_wrong_password_does_not_verify(self):
        hashed = hash_password("correct horse battery staple")
        assert not verify_password("wrong password", hashed)

    def test_the_hash_never_contains_the_plaintext(self):
        password = "hunter2"
        assert password not in hash_password(password)

    def test_the_same_password_hashes_differently_each_time(self):
        """bcrypt salts per call; two hashes of the same password must differ."""
        assert hash_password("hunter2") != hash_password("hunter2")

    def test_a_malformed_stored_hash_fails_closed(self):
        assert not verify_password("anything", "not-a-real-bcrypt-hash")


class TestTokens:
    def test_a_freshly_issued_token_decodes_to_the_same_subject_and_role(self):
        token = create_access_token(settings(), "alice", "trader")
        payload = decode_access_token(settings(), token)
        assert payload.subject == "alice"
        assert payload.role == "trader"

    def test_a_token_signed_with_a_different_secret_is_rejected(self):
        token = create_access_token(settings(jwt_secret="secret-a"), "alice", "trader")
        with pytest.raises(InvalidToken, match="invalid"):
            decode_access_token(settings(jwt_secret="secret-b"), token)

    def test_an_expired_token_is_rejected(self):
        cfg = settings()
        # Hand-craft an already-expired token using the same secret and claim shape.
        import time

        payload = {
            "sub": "alice",
            "role": "trader",
            "iat": int(time.time()) - 3600,
            "exp": int(time.time()) - 1800,
        }
        expired = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")
        with pytest.raises(InvalidToken, match="expired"):
            decode_access_token(cfg, expired)

    def test_a_token_missing_a_required_claim_is_rejected(self):
        cfg = settings()
        malformed = jwt.encode({"sub": "alice"}, cfg.jwt_secret, algorithm="HS256")
        with pytest.raises(InvalidToken, match="missing required claim"):
            decode_access_token(cfg, malformed)

    def test_a_garbage_string_is_rejected(self):
        with pytest.raises(InvalidToken):
            decode_access_token(settings(), "not.a.token")

    def test_expiry_respects_the_configured_window(self):
        cfg = settings(jwt_expiry_minutes=5)
        token = create_access_token(cfg, "alice", "viewer")
        payload = decode_access_token(cfg, token)
        delta = payload.expires_at - payload.issued_at
        assert abs(delta - timedelta(minutes=5)) < timedelta(seconds=2)


class TestRoleHierarchy:
    @pytest.mark.parametrize(
        ("actual", "required"),
        [
            (Role.ADMIN, Role.VIEWER),
            (Role.ADMIN, Role.TRADER),
            (Role.ADMIN, Role.ADMIN),
            (Role.TRADER, Role.VIEWER),
            (Role.TRADER, Role.TRADER),
            (Role.VIEWER, Role.VIEWER),
        ],
    )
    def test_a_sufficient_role_satisfies_the_requirement(self, actual, required):
        assert satisfies(actual, required)

    @pytest.mark.parametrize(
        ("actual", "required"),
        [
            (Role.VIEWER, Role.TRADER),
            (Role.VIEWER, Role.ADMIN),
            (Role.TRADER, Role.ADMIN),
        ],
    )
    def test_an_insufficient_role_does_not_satisfy_the_requirement(self, actual, required):
        assert not satisfies(actual, required)


class TestProductionSecretGuard:
    def test_production_refuses_the_placeholder_secret(self):
        with pytest.raises(ValueError, match="JWT_SECRET must be set"):
            settings(app_env="production", jwt_secret="dev-only-insecure-secret-change-me")

    def test_production_accepts_a_real_secret(self):
        settings(app_env="production", jwt_secret="a-real-generated-secret")

    def test_development_accepts_the_placeholder(self):
        settings(app_env="development", jwt_secret="dev-only-insecure-secret-change-me")
