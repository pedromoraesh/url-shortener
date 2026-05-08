import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB = "sqlite:///./test_rate_limiting.db"
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


class TestShortenRateLimit:
    """Rate limiting tests for POST /shorten (limit: 10/minute)"""

    def test_shorten_within_limit(self):
        client = TestClient(app)
        response = client.post(
            "/shorten",
            json={"original_url": "https://example.com"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
        assert response.status_code in (200, 201, 422)

    def test_shorten_rate_limit_exceeded(self):
        client = TestClient(app)
        responses = []
        for i in range(11):
            resp = client.post(
                "/shorten",
                json={"original_url": f"https://example{i}.com"},
                headers={"X-Forwarded-For": "192.168.100.1"},
            )
            responses.append(resp)

        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, f"Expected at least one 429, got: {status_codes}"

    def test_shorten_429_has_retry_after_header(self):
        client = TestClient(app)
        for i in range(11):
            resp = client.post(
                "/shorten",
                json={"original_url": f"https://test{i}.com"},
                headers={"X-Forwarded-For": "192.168.200.1"},
            )
            if resp.status_code == 429:
                headers_lower = {k.lower(): v for k, v in resp.headers.items()}
                assert "retry-after" in headers_lower, (
                    f"Retry-After header missing. Headers: {dict(resp.headers)}"
                )
                return

        pytest.fail("Rate limit was not reached in 11 requests — check limiter config")


class TestRedirectRateLimit:
    """Rate limiting tests for GET /{code} (limit: 60/minute)"""

    def test_redirect_within_limit(self):
        client = TestClient(app)
        response = client.get(
            "/testcode",
            headers={"X-Forwarded-For": "10.0.0.1"},
            follow_redirects=False,
        )
        assert response.status_code != 429, (
            f"First request should not return 429, got {response.status_code}"
        )

    def test_redirect_rate_limit_exceeded(self):
        client = TestClient(app)
        responses = []
        for i in range(61):
            resp = client.get(
                "/testcode",
                headers={"X-Forwarded-For": "10.0.0.2"},
                follow_redirects=False,
            )
            responses.append(resp)

        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, (
            f"Expected at least one 429 after 61 requests, got: {status_codes}"
        )

    def test_redirect_429_has_retry_after_header(self):
        client = TestClient(app)
        for i in range(61):
            resp = client.get(
                "/testcode",
                headers={"X-Forwarded-For": "10.0.0.3"},
                follow_redirects=False,
            )
            if resp.status_code == 429:
                headers_lower = {k.lower(): v for k, v in resp.headers.items()}
                assert "retry-after" in headers_lower, (
                    f"Retry-After header missing. Headers: {dict(resp.headers)}"
                )
                return

        pytest.fail("Rate limit of 60 was not reached in 61 requests — check limiter config")
