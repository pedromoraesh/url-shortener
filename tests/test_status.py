from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_get_status_returns_200():
    response = client.get("/status")
    assert response.status_code == 200


def test_get_status_returns_correct_json():
    response = client.get("/status")
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "url-shortener"
