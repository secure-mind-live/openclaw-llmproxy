from fastapi.testclient import TestClient
from proxy.main import app


class TestWebDashboard:
    client = TestClient(app)

    def test_dashboard_returns_html(self):
        resp = self.client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "OpenClaw" in resp.text

    def test_metrics_returns_json(self):
        resp = self.client.get("/dashboard/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "request_count" in data
        assert "avg_latency_ms" in data
        assert "error_rate" in data
        assert "cache" in data
        assert "spend" in data
        assert "requests_by_backend" in data

    def test_dashboard_exempt_from_auth(self):
        from unittest.mock import patch
        with patch("proxy.auth.PROXY_API_KEY", "secret123"):
            client = TestClient(app)
            resp = client.get("/dashboard")
            assert resp.status_code == 200

    def test_metrics_exempt_from_auth(self):
        from unittest.mock import patch
        with patch("proxy.auth.PROXY_API_KEY", "secret123"):
            client = TestClient(app)
            resp = client.get("/dashboard/metrics")
            assert resp.status_code == 200
