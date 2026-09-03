"""End-to-end auth: login, RBAC enforcement, and the bootstrap admin.

Marked integration -- exercises the real API against a live Postgres, the
same way tests/test_db_roundtrip.py does.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth.roles import Role
from app.auth.security import hash_password
from app.db.repositories import UserRepository
from app.db.session import session_scope
from app.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    # The login rate limiter is a module-level singleton independent of how
    # many app instances are created; reset it so one test's login attempts
    # cannot exhaust another test's budget.
    from app.api.routes.auth import limiter as login_limiter

    login_limiter.reset()
    return TestClient(create_app())


def make_user(username: str, password: str, role: Role) -> str:
    """Create a user directly via the repository and return their username."""
    with session_scope() as session:
        UserRepository(session).create(username, hash_password(password), role.value)
    return username


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestLogin:
    def test_correct_credentials_issue_a_token(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "correct-password", Role.VIEWER)
        response = client.post(
            "/api/auth/login", json={"username": username, "password": "correct-password"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "viewer"
        assert body["token_type"] == "bearer"
        assert len(body["access_token"]) > 20

    def test_wrong_password_is_rejected(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "correct-password", Role.VIEWER)
        response = client.post(
            "/api/auth/login", json={"username": username, "password": "wrong"}
        )
        assert response.status_code == 401

    def test_unknown_username_gives_the_same_generic_error(self, client):
        """Distinguishing 'no such user' from 'wrong password' would leak
        which usernames exist to anyone probing.
        """
        response = client.post(
            "/api/auth/login", json={"username": "definitely-not-a-user", "password": "x"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid username or password"

    def test_a_deactivated_account_cannot_log_in(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "correct-password", Role.VIEWER)
        with session_scope() as session:
            user = UserRepository(session).get_by_username(username)
            user.is_active = False

        response = client.post(
            "/api/auth/login", json={"username": username, "password": "correct-password"}
        )
        assert response.status_code == 401


class TestProtectedRoutes:
    def test_no_token_is_rejected(self, client):
        assert client.get("/api/overview").status_code == 401

    def test_a_malformed_token_is_rejected(self, client):
        response = client.get("/api/overview", headers=auth_headers("not-a-real-token"))
        assert response.status_code == 401

    def test_a_valid_token_is_accepted(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "correct-password", Role.VIEWER)
        token = login(client, username, "correct-password")
        response = client.get("/api/overview", headers=auth_headers(token))
        assert response.status_code == 200

    def test_health_and_ready_need_no_token(self, client):
        """The orchestrator's healthcheck must work with no credentials."""
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code in (200, 503)


class TestRBAC:
    def test_a_viewer_can_read_the_dashboard(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        token = login(client, username, "pw")
        assert client.get("/api/portfolio", headers=auth_headers(token)).status_code == 200

    def test_a_viewer_cannot_run_a_backtest(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        token = login(client, username, "pw")
        response = client.post(
            "/api/backtest",
            json={"strategy": "ema_crossover", "symbol": "BTCUSDT"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    def test_a_trader_can_attempt_a_backtest(self, client):
        """403 must not fire for a trader -- whatever status follows is about
        data availability, not permission.
        """
        username = make_user(f"trader-{uuid.uuid4().hex[:8]}", "pw", Role.TRADER)
        token = login(client, username, "pw")
        response = client.post(
            "/api/backtest",
            json={"strategy": "ema_crossover", "symbol": "BTCUSDT"},
            headers=auth_headers(token),
        )
        assert response.status_code != 403

    def test_a_viewer_cannot_create_users(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        token = login(client, username, "pw")
        response = client.post(
            "/api/auth/users",
            json={"username": "new-user", "password": "password123"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    def test_a_trader_cannot_create_users(self, client):
        username = make_user(f"trader-{uuid.uuid4().hex[:8]}", "pw", Role.TRADER)
        token = login(client, username, "pw")
        response = client.post(
            "/api/auth/users",
            json={"username": "new-user", "password": "password123"},
            headers=auth_headers(token),
        )
        assert response.status_code == 403

    def test_an_admin_can_create_users(self, client):
        admin_username = make_user(f"admin-{uuid.uuid4().hex[:8]}", "pw", Role.ADMIN)
        token = login(client, admin_username, "pw")
        new_username = f"created-{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/auth/users",
            json={"username": new_username, "password": "password123", "role": "trader"},
            headers=auth_headers(token),
        )
        assert response.status_code == 201
        assert response.json() == {"username": new_username, "role": "trader"}

    def test_creating_a_duplicate_username_conflicts(self, client):
        admin_username = make_user(f"admin-{uuid.uuid4().hex[:8]}", "pw", Role.ADMIN)
        token = login(client, admin_username, "pw")
        response = client.post(
            "/api/auth/users",
            json={"username": admin_username, "password": "password123"},
            headers=auth_headers(token),
        )
        assert response.status_code == 409

    def test_only_admin_can_read_the_audit_log(self, client):
        viewer = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        admin = make_user(f"admin-{uuid.uuid4().hex[:8]}", "pw", Role.ADMIN)

        viewer_token = login(client, viewer, "pw")
        admin_token = login(client, admin, "pw")

        assert client.get("/api/audit", headers=auth_headers(viewer_token)).status_code == 403
        assert client.get("/api/audit", headers=auth_headers(admin_token)).status_code == 200


class TestMe:
    def test_returns_the_authenticated_users_identity(self, client):
        username = make_user(f"trader-{uuid.uuid4().hex[:8]}", "pw", Role.TRADER)
        token = login(client, username, "pw")
        response = client.get("/api/auth/me", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json() == {"username": username, "role": "trader"}


class TestAuditTrail:
    def test_a_login_is_recorded_in_the_audit_log(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        login(client, username, "pw")

        admin = make_user(f"admin-{uuid.uuid4().hex[:8]}", "pw", Role.ADMIN)
        admin_token = login(client, admin, "pw")

        entries = client.get(
            "/api/audit?limit=500", headers=auth_headers(admin_token)
        ).json()
        assert any(
            e["action"] == "auth.login" and e["entity_id"] == username for e in entries
        )

    def test_a_failed_login_is_also_recorded(self, client):
        username = make_user(f"viewer-{uuid.uuid4().hex[:8]}", "pw", Role.VIEWER)
        client.post("/api/auth/login", json={"username": username, "password": "wrong"})

        admin = make_user(f"admin-{uuid.uuid4().hex[:8]}", "pw", Role.ADMIN)
        admin_token = login(client, admin, "pw")

        entries = client.get(
            "/api/audit?limit=500", headers=auth_headers(admin_token)
        ).json()
        assert any(
            e["action"] == "auth.login_failed" and e["entity_id"] == username
            for e in entries
        )
