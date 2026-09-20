from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FakePool

SETTINGS = Settings(database_url="postgresql://unused", cors_origins="http://localhost:5173")


def client_with(pool: FakePool) -> TestClient:
    return TestClient(create_app(SETTINGS, pool_factory=lambda _settings: pool))


def test_health_is_ok_when_postgis_answers() -> None:
    with client_with(FakePool(row=("3.5.1",))) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "postgis": "3.5.1", "detail": None}


def test_health_is_503_when_database_is_down() -> None:
    with client_with(FakePool(error=OSError("connection refused"))) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert body["detail"] == "connection refused"


def test_health_is_503_when_postgis_extension_is_missing() -> None:
    with client_with(FakePool(row=None)) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["database"] == "ok"


def test_lifespan_opens_and_closes_the_pool() -> None:
    pool = FakePool(row=("3.5.1",))

    with client_with(pool) as client:
        client.get("/api/health")
        assert pool.opened

    assert pool.closed
