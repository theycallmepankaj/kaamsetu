import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.limiter import limiter

    limiter.reset()
    yield
