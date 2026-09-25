from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_ok_with_db_up() -> None:
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}
