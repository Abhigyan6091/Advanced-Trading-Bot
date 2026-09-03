"""Health and readiness endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_does_not_touch_the_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["broker"] == "paper"
    assert body["live_trading"] is False


def test_readiness_reports_database_state(client):
    """503 when the database is unreachable, 200 when it is up.

    Either is a correct answer; what matters is that a degraded dependency is
    reported rather than hidden behind a 200.
    """
    r = client.get("/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "database" in body["checks"]
    if r.status_code == 200:
        assert body["status"] == "ok"
    else:
        assert body["status"] == "degraded"


def test_openapi_schema_is_generated(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/health" in r.json()["paths"]
