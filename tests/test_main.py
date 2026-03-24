from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient


class TestHealthEndpoint:
    async def test_returns_ok(self):
        from proxy_voter.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAppRoutes:
    def test_includes_webhook_route(self):
        from proxy_voter.main import app

        paths = [route.path for route in app.routes]
        assert "/webhook/email" in paths
        assert "/health" in paths


class TestLifespan:
    async def test_calls_init_db(self):
        from proxy_voter.main import app, lifespan

        with patch("proxy_voter.main.init_db", new_callable=AsyncMock) as mock_init:
            async with lifespan(app):
                pass
        mock_init.assert_awaited_once()
