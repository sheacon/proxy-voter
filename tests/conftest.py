import os

import pytest

# Set test env vars before any imports that need settings
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("RESEND_API_KEY", "test-key")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("FROM_EMAIL", "proxy-voter@example.com")
os.environ.setdefault("APPROVED_SENDERS", "user@example.com,user2@example.com")
os.environ.setdefault("DATABASE_PATH", "test_data/proxy_voter.db")


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset the cached settings singleton between tests."""
    import proxy_voter.config

    proxy_voter.config._settings = None
    yield
    proxy_voter.config._settings = None
