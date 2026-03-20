"""Tests for the API gateway."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def client():
    with patch("quantpulse_api.app.asyncpg.create_pool", new_callable=AsyncMock), \
         patch("quantpulse_api.app.aioredis.from_url", new_callable=AsyncMock), \
         patch("quantpulse_api.app._regime_broadcast_loop", new_callable=AsyncMock):
        from quantpulse_api.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_login_requires_credentials(client):
    resp = client.post("/auth/token", data={"username": "", "password": ""})
    assert resp.status_code == 400


def test_login_returns_token(client):
    resp = client.post("/auth/token", data={"username": "demo", "password": "demo"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_protected_endpoint_requires_auth(client):
    resp = client.get("/api/v1/regime")
    assert resp.status_code == 401
