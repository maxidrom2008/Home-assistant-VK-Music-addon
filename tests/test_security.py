from fastapi.testclient import TestClient

from app.main import app


def test_ingress_proxy_is_allowed_and_direct_clients_are_blocked() -> None:
    with TestClient(app, client=("172.30.32.2", 50000)) as ingress_client:
        assert ingress_client.get("/api/v1/status").status_code == 200

    with TestClient(app, client=("192.0.2.25", 50000)) as external_client:
        assert external_client.get("/api/v1/status").status_code == 403
        assert external_client.get("/health").status_code == 200
