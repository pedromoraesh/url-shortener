import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB = "sqlite:///./test_urls.db"
engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


client = TestClient(app)


def test_shorten_url_basic():
    resp = client.post("/shorten", json={"original_url": "https://example.com"})
    assert resp.status_code == 201
    data = resp.json()
    assert "short_code" in data
    assert data["expires_at"] is None


def test_shorten_url_with_expiration():
    resp = client.post("/shorten", json={"original_url": "https://example.com", "expires_in_hours": 24})
    assert resp.status_code == 201
    data = resp.json()
    assert data["expires_at"] is not None


def test_redirect_valid():
    resp = client.post("/shorten", json={"original_url": "https://example.com"})
    code = resp.json()["short_code"]
    resp2 = client.get(f"/{code}", follow_redirects=False)
    assert resp2.status_code == 302
    assert resp2.headers["location"] in ("https://example.com", "https://example.com/")


def test_redirect_not_found():
    resp = client.get("/nonexistent", follow_redirects=False)
    assert resp.status_code == 404


def test_redirect_expired():
    from app.models import URL
    from app.database import SessionLocal
    db = TestingSession()
    url_obj = URL(
        original_url="https://example.com",
        short_code="expired",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    db.add(url_obj)
    db.commit()
    db.close()

    resp = client.get("/expired", follow_redirects=False)
    assert resp.status_code == 410
    assert resp.json()["detail"] == "URL has expired"


def test_redirect_not_yet_expired():
    from app.models import URL
    db = TestingSession()
    url_obj = URL(
        original_url="https://example.com",
        short_code="future",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(url_obj)
    db.commit()
    db.close()

    resp = client.get("/future", follow_redirects=False)
    assert resp.status_code == 302
