"""
QA tests for JWT authentication — PR #3
Acceptance criteria:
  1. Duplicate email registration returns error (400)
  2. Login with wrong password returns 401
  3. Protected endpoint without token returns 401
  4. Owner can delete their own URL (204)
  5. Non-owner cannot delete another user's URL (403)
"""
import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB = "sqlite:///./test_jwt_auth.db"
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def unique_email():
    return f"qa_{uuid.uuid4().hex[:8]}@test.com"


PASSWORD = "SecurePass123!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def register_user(client, email, password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login_user(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_headers(client, email, password=PASSWORD):
    r = login_user(client, email, password)
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"No token in response: {r.json()}"
    return {"Authorization": f"Bearer {token}"}


def shorten_url(client, headers, url="https://example.com"):
    # Schema uses `original_url`, not `url`
    r = client.post("/shorten", json={"original_url": url}, headers=headers)
    assert r.status_code in (200, 201), f"Shorten failed: {r.text}"
    data = r.json()
    short_code = (
        data.get("short_code")
        or data.get("short")
        or data.get("alias")
        or data.get("code")
        or data.get("id")
    )
    assert short_code, f"No short code in response: {data}"
    return short_code


def delete_url(client, short_code, headers=None):
    for path in [f"/my/urls/{short_code}", f"/urls/{short_code}"]:
        r = client.delete(path, headers=headers or {})
        if r.status_code != 404:
            return r
    return r


# ---------------------------------------------------------------------------
# Criterion 1 — Duplicate email registration returns error (400)
# ---------------------------------------------------------------------------

def test_duplicate_email_returns_error(client):
    email = unique_email()
    r1 = register_user(client, email)
    assert r1.status_code in (200, 201), f"First registration failed: {r1.text}"

    r2 = register_user(client, email)
    assert r2.status_code == 400, (
        f"Expected 400 for duplicate email, got {r2.status_code}. Body: {r2.text}"
    )


# ---------------------------------------------------------------------------
# Criterion 2 — Login with wrong password returns 401
# ---------------------------------------------------------------------------

def test_login_wrong_password_returns_401(client):
    email = unique_email()
    r = register_user(client, email)
    assert r.status_code in (200, 201), f"Registration failed: {r.text}"

    r2 = login_user(client, email, password="WrongPassword!")
    assert r2.status_code == 401, (
        f"Expected 401 for wrong password, got {r2.status_code}. Body: {r2.text}"
    )


# ---------------------------------------------------------------------------
# Criterion 3 — Protected endpoint without token returns 401
# ---------------------------------------------------------------------------

def test_protected_endpoint_no_token_returns_401(client):
    # GET /my/urls requires authentication (get_required_current_user)
    r = client.get("/my/urls")
    assert r.status_code == 401, (
        f"Expected 401 for unauthenticated GET /my/urls, got {r.status_code}. Body: {r.text}"
    )


def test_delete_without_token_returns_401(client):
    # DELETE without auth returns 401 before route body executes
    r = delete_url(client, "somenonexistentslug", headers=None)
    assert r.status_code == 401, (
        f"Expected 401 for unauthenticated delete, got {r.status_code}. Body: {r.text}"
    )


# ---------------------------------------------------------------------------
# Criterion 4 — Owner can delete their own URL (204)
# ---------------------------------------------------------------------------

def test_owner_can_delete_own_url(client):
    email = unique_email()
    register_user(client, email)
    headers = auth_headers(client, email)

    short_code = shorten_url(client, headers)
    r = delete_url(client, short_code, headers=headers)
    assert r.status_code == 204, (
        f"Expected 204 when owner deletes own URL, got {r.status_code}. Body: {r.text}"
    )


# ---------------------------------------------------------------------------
# Criterion 5 — Non-owner cannot delete another user's URL (403)
# ---------------------------------------------------------------------------

def test_non_owner_cannot_delete_url(client):
    # User A creates a URL
    email_a = unique_email()
    register_user(client, email_a)
    headers_a = auth_headers(client, email_a)
    short_code = shorten_url(client, headers_a)

    # User B tries to delete User A's URL
    email_b = unique_email()
    register_user(client, email_b)
    headers_b = auth_headers(client, email_b)

    r = delete_url(client, short_code, headers=headers_b)
    assert r.status_code == 403, (
        f"Expected 403 when non-owner tries to delete, got {r.status_code}. Body: {r.text}"
    )
