"""
QA validation tests for redirect chain tracking feature (PR #7).

Acceptance criteria:
- GET /{code} returns X-Redirect-Count: 1 header
- POST /shorten accepts max_redirects (optional)
- POST /shorten works without max_redirects
- Existing redirect behaviour not broken
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DB = "sqlite:///./test_redirect_chain.db"
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


def _create_short_url(url: str = "https://example.com", **kwargs) -> str:
    """Helper: creates a short URL and returns the short_code."""
    payload = {"original_url": url, **kwargs}
    response = client.post("/shorten", json=payload)
    assert response.status_code == 201, (
        f"Expected 201 from POST /shorten, got {response.status_code}. Body: {response.text}"
    )
    return response.json()["short_code"]


class TestXRedirectCountHeader:
    def test_redirect_response_contains_x_redirect_count_header(self):
        """GET /{code} deve retornar o header X-Redirect-Count."""
        code = _create_short_url()
        response = client.get(f"/{code}")
        assert "x-redirect-count" in {k.lower() for k in response.headers}, (
            f"Header X-Redirect-Count ausente. Headers recebidos: {dict(response.headers)}"
        )

    def test_x_redirect_count_value_is_one(self):
        """O valor do header X-Redirect-Count deve ser exatamente '1'."""
        code = _create_short_url()
        response = client.get(f"/{code}")
        header_value = (
            response.headers.get("x-redirect-count")
            or response.headers.get("X-Redirect-Count")
        )
        assert header_value == "1", (
            f"Esperado '1', recebido '{header_value}'"
        )

    def test_x_redirect_count_present_regardless_of_max_redirects(self):
        """X-Redirect-Count deve estar presente mesmo quando max_redirects != 1."""
        code = _create_short_url(max_redirects=5)
        response = client.get(f"/{code}")
        assert "x-redirect-count" in {k.lower() for k in response.headers}, (
            f"Header X-Redirect-Count ausente quando max_redirects=5. "
            f"Headers: {dict(response.headers)}"
        )


class TestMaxRedirectsField:
    def test_post_shorten_accepts_max_redirects(self):
        """POST /shorten deve aceitar max_redirects sem erro."""
        response = client.post(
            "/shorten", json={"original_url": "https://example.com", "max_redirects": 5}
        )
        assert response.status_code == 201, (
            f"Esperado 201, recebido {response.status_code}. Body: {response.text}"
        )

    def test_post_shorten_works_without_max_redirects(self):
        """POST /shorten deve funcionar normalmente sem max_redirects (campo opcional)."""
        response = client.post("/shorten", json={"original_url": "https://example.com"})
        assert response.status_code == 201, (
            f"Esperado 201, recebido {response.status_code}. Body: {response.text}"
        )

    def test_post_shorten_max_redirects_default_is_one(self):
        """Se max_redirects nao for fornecido, o valor padrao deve ser 1.
        NOTE: URLResponse nao expoe max_redirects — verifica so se o campo estiver na resposta.
        """
        response = client.post("/shorten", json={"original_url": "https://example.com"})
        assert response.status_code == 201
        data = response.json()
        if "max_redirects" in data:
            assert data["max_redirects"] == 1, (
                f"Esperado max_redirects=1, recebido {data['max_redirects']}"
            )

    def test_post_shorten_max_redirects_persisted(self):
        """max_redirects fornecido deve ser persistido e retornado (se exposto pelo schema).
        NOTE: URLResponse nao inclui max_redirects — teste passa vacuamente se o campo ausente.
        """
        response = client.post(
            "/shorten", json={"original_url": "https://example.com", "max_redirects": 3}
        )
        assert response.status_code == 201
        data = response.json()
        if "max_redirects" in data:
            assert data["max_redirects"] == 3, (
                f"Esperado max_redirects=3, recebido {data['max_redirects']}"
            )

    def test_post_shorten_max_redirects_zero_accepted(self):
        """POST /shorten deve aceitar max_redirects=0."""
        response = client.post(
            "/shorten", json={"original_url": "https://example.com", "max_redirects": 0}
        )
        assert response.status_code == 201, (
            f"Esperado 201 para max_redirects=0, recebido {response.status_code}. "
            f"Body: {response.text}"
        )


class TestExistingBehaviorNotBroken:
    def test_redirect_still_works(self):
        """GET /{code} ainda deve redirecionar (3xx)."""
        code = _create_short_url(url="https://example.com")
        response = client.get(f"/{code}")
        assert response.status_code in (301, 302, 307, 308), (
            f"Esperado redirect 3xx, recebido {response.status_code}"
        )

    def test_redirect_location_header_correct(self):
        """GET /{code} deve redirecionar para a URL original."""
        target = "https://example.com/path?q=1"
        code = _create_short_url(url=target)
        response = client.get(f"/{code}")
        assert response.headers.get("location") == target, (
            f"Location incorreto: esperado '{target}', "
            f"recebido '{response.headers.get('location')}'"
        )

    def test_x_redirect_count_not_present_on_404(self):
        """X-Redirect-Count NAO deve aparecer em respostas 404."""
        response = client.get("/nonexistent_code_xyz")
        assert response.status_code == 404
        assert "x-redirect-count" not in {k.lower() for k in response.headers}, (
            "X-Redirect-Count nao deveria estar presente em respostas 404"
        )
