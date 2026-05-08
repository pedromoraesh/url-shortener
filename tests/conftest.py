import pytest
from app.main import limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter._storage.reset()
    yield
    limiter._storage.reset()
