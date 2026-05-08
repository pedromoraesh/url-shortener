"""
Security contract tests for url-shortener.
These tests document the security behavior of the API.
They will FAIL if a security regression is introduced.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB = "sqlite:///./test_security.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=_engine)
    app.dependency_overrides[get_db] = _override_get_db
    yield
    Base.metadata.drop_all(bind=_engine)
    app.dependency_overrides.clear()


client = TestClient(app, follow_redirects=False)


class TestSSRFProtection:
    """A10 -- SSRF: URL scheme validation"""

    def test_post_shorten_rejects_file_scheme(self):
        """Should reject file:// URLs -- Pydantic HttpUrl only allows http/https."""
        resp = client.post("/shorten", json={"original_url": "file:///etc/passwd"})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for file:// URL, got {resp.status_code}. Body: {resp.text}"
        )

    def test_post_shorten_rejects_javascript_scheme(self):
        """Should reject javascript: URLs -- Pydantic HttpUrl only allows http/https."""
        resp = client.post("/shorten", json={"original_url": "javascript:alert(1)"})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for javascript: URL, got {resp.status_code}. Body: {resp.text}"
        )

    def test_post_shorten_rejects_ftp_scheme(self):
        """Should reject ftp:// URLs -- Pydantic HttpUrl only allows http/https."""
        resp = client.post("/shorten", json={"original_url": "ftp://example.com/file"})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for ftp:// URL, got {resp.status_code}. Body: {resp.text}"
        )

    @pytest.mark.xfail(
        reason="FINDING: Internal network IPs not blocked. "
               "http://169.254.169.254 is a valid http:// URL per Pydantic HttpUrl. "
               "Service can redirect clients to internal metadata endpoints.",
        strict=True,
    )
    def test_post_shorten_rejects_internal_ip(self):
        """Should reject internal network addresses (AWS metadata endpoint)."""
        resp = client.post(
            "/shorten", json={"original_url": "http://169.254.169.254/latest/meta-data/"}
        )
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for internal IP, got {resp.status_code}. Body: {resp.text}"
        )

    def test_post_shorten_accepts_valid_https_url(self):
        """Valid https:// URLs must be accepted."""
        resp = client.post("/shorten", json={"original_url": "https://example.com"})
        assert resp.status_code == 201, (
            f"Expected 201 for valid https URL, got {resp.status_code}. Body: {resp.text}"
        )

    def test_post_shorten_accepts_valid_http_url(self):
        """Valid http:// URLs must be accepted."""
        resp = client.post("/shorten", json={"original_url": "http://example.com"})
        assert resp.status_code == 201, (
            f"Expected 201 for valid http URL, got {resp.status_code}. Body: {resp.text}"
        )


class TestInputValidation:
    """A03/A04 -- Input validation"""

    @pytest.mark.xfail(
        reason="FINDING: max_redirects has no lower bound validation in URLCreate schema. "
               "Negative values are accepted (no Field(ge=0) constraint). "
               "Fix: max_redirects: Optional[int] = Field(default=1, ge=0) in schemas.py",
        strict=True,
    )
    def test_max_redirects_rejects_negative_value(self):
        """max_redirects must not accept negative integers -- no ge=0 constraint exists."""
        resp = client.post("/shorten", json={"original_url": "https://example.com", "max_redirects": -1})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for max_redirects=-1, got {resp.status_code}. Body: {resp.text}"
        )

    @pytest.mark.xfail(
        reason="FINDING: max_redirects has no upper bound. "
               "Arbitrarily large values accepted. "
               "Fix: add le=100 or similar constraint in Field() definition.",
        strict=True,
    )
    def test_max_redirects_rejects_excessively_large_value(self):
        """max_redirects must have an upper bound to prevent misuse."""
        resp = client.post("/shorten", json={"original_url": "https://example.com", "max_redirects": 99999})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for max_redirects=99999, got {resp.status_code}. Body: {resp.text}"
        )

    def test_url_field_rejects_empty_string(self):
        """Empty URL must be rejected by Pydantic HttpUrl validation."""
        resp = client.post("/shorten", json={"original_url": ""})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for empty URL, got {resp.status_code}. Body: {resp.text}"
        )

    def test_url_field_has_max_length(self):
        """Pydantic HttpUrl enforces max 2083 chars (RFC limit) -- URLs over this are rejected."""
        long_url = "https://example.com/" + "a" * 3000
        resp = client.post("/shorten", json={"original_url": long_url})
        assert resp.status_code in (422, 400), (
            f"Expected 422/400 for URL > 2083 chars, got {resp.status_code}. Body: {resp.text}"
        )


class TestEnumeration:
    """A01 -- Broken Access Control: code enumeration"""

    def test_unknown_code_returns_404(self):
        """Non-existent code must return 404, not 500 or other error that leaks info."""
        resp = client.get("/xxxxxx", follow_redirects=False)
        assert resp.status_code == 404, (
            f"Expected 404 for unknown code, got {resp.status_code}. Body: {resp.text}"
        )
        data = resp.json()
        assert "detail" in data
        assert "stack" not in resp.text.lower(), "Response must not contain stack trace"
        assert "traceback" not in resp.text.lower(), "Response must not contain traceback"

    def test_sequential_codes_not_predictable(self):
        """
        FINDING: _generate_code() uses random.choices (Mersenne Twister) not secrets.
        Documents that codes are at least not sequentially numeric/alphabetic.
        Fix: replace random.choices with secrets.choices in main.py _generate_code().
        """
        codes = []
        for _ in range(5):
            resp = client.post("/shorten", json={"original_url": "https://example.com"})
            assert resp.status_code == 201
            codes.append(resp.json()["short_code"])

        assert not all(c.isdigit() for c in codes), "Codes must not be purely numeric"
        assert len(set(codes)) > 1, "Codes must be unique across requests"
        assert all(len(c) == 6 for c in codes), "Codes must be 6 characters long"


class TestSecurityHeaders:
    """Security headers on redirect response"""

    def test_redirect_response_has_x_redirect_count(self):
        """X-Redirect-Count header must be present on redirect response."""
        resp = client.post("/shorten", json={"original_url": "https://example.com"})
        assert resp.status_code == 201
        code = resp.json()["short_code"]

        redirect_resp = client.get(f"/{code}", follow_redirects=False)
        assert redirect_resp.status_code == 302
        assert "x-redirect-count" in {k.lower() for k in redirect_resp.headers}, (
            f"X-Redirect-Count header missing. Headers: {dict(redirect_resp.headers)}"
        )

    def test_redirect_does_not_leak_server_header_version(self):
        """Server header must not expose detailed version information."""
        resp = client.post("/shorten", json={"original_url": "https://example.com"})
        code = resp.json()["short_code"]
        redirect_resp = client.get(f"/{code}", follow_redirects=False)
        server_header = redirect_resp.headers.get("server", "")
        assert "/" not in server_header, (
            f"Server header exposes version: '{server_header}'"
        )

    def test_404_does_not_expose_stack_trace(self):
        """404 responses must not contain stack traces or internal paths."""
        resp = client.get("/nonexistentcode123", follow_redirects=False)
        assert resp.status_code == 404
        body = resp.text
        assert "Traceback" not in body
        assert "File \"/app" not in body
        assert "raise HTTPException" not in body


class TestRateLimiting:
    """A07 -- Rate limiting (documented absence)"""

    @pytest.mark.xfail(
        reason="FINDING: No rate limiting on POST /shorten. "
               "20 rapid requests all succeed with 201. "
               "An attacker can flood the database with unlimited shortened URLs. "
               "Fix: add slowapi or similar middleware with per-IP limits.",
        strict=True,
    )
    def test_post_shorten_rate_limit_documented(self):
        """Rate limiting should eventually block excessive POST /shorten requests."""
        responses = [
            client.post("/shorten", json={"original_url": "https://example.com"})
            for _ in range(20)
        ]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, (
            f"All 20 POST /shorten requests succeeded -- no rate limiting. "
            f"Status codes: {status_codes}"
        )

    @pytest.mark.xfail(
        reason="FINDING: No rate limiting on GET /{code}. "
               "Brute-force enumeration feasible, especially combined with "
               "non-cryptographic random.choices (Mersenne Twister) code generation. "
               "Fix: add rate limiting + replace random.choices with secrets.choices.",
        strict=True,
    )
    def test_get_redirect_rate_limit_documented(self):
        """Rate limiting should block brute-force enumeration on GET /{code}."""
        responses = [
            client.get("/aaaaaa", follow_redirects=False)
            for _ in range(20)
        ]
        status_codes = [r.status_code for r in responses]
        assert 429 in status_codes, (
            f"All 20 GET requests succeeded -- no rate limiting. "
            f"Status codes: {status_codes}"
        )
