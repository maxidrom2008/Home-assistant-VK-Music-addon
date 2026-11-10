from fastapi.testclient import TestClient
from app.main import app

def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_auth_is_explicitly_unconfigured() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
