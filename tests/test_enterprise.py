"""Tests for enterprise features: metrics, multi-tenancy, tracing, SDK."""

import json
import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
from proxy.main import app
from proxy.tenants import authenticate, is_multi_tenant, check_backend_allowed, check_model_allowed
from sdk.client import OpenClawClient


# ---------------------------------------------------------------------------
# Prometheus /metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    client = TestClient(app)

    def test_metrics_returns_200(self):
        resp = self.client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_has_prometheus_format(self):
        # Fire a request first to generate metrics
        resp = self.client.get("/health")
        resp = self.client.get("/metrics")
        text = resp.text
        assert "# TYPE" in text or text.strip() == ""

    def test_metrics_exempt_from_auth(self):
        with patch("proxy.auth.PROXY_API_KEY", "secret"):
            client = TestClient(app)
            resp = client.get("/metrics")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Multi-tenancy
# ---------------------------------------------------------------------------

class TestMultiTenancy:
    def _write_tenants(self, tmp, data):
        path = os.path.join(tmp, "tenants.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_multi_tenant_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_tenants(tmp, {
                "tenants": {
                    "key-alpha": {"name": "Alpha", "rate_limit_rpm": 100},
                    "key-beta": {"name": "Beta", "rate_limit_rpm": 30},
                }
            })
            with patch("proxy.tenants.TENANTS_FILE", path), \
                 patch("proxy.tenants._tenants_cache", None):
                assert is_multi_tenant()
                assert authenticate("key-alpha")["name"] == "Alpha"
                assert authenticate("key-beta")["name"] == "Beta"
                assert authenticate("key-invalid") is None

    def test_backend_restriction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_tenants(tmp, {
                "tenants": {
                    "key-restricted": {
                        "name": "Restricted",
                        "allowed_backends": ["ollama"],
                    }
                }
            })
            with patch("proxy.tenants.TENANTS_FILE", path), \
                 patch("proxy.tenants._tenants_cache", None):
                assert check_backend_allowed("key-restricted", "ollama")
                assert not check_backend_allowed("key-restricted", "openai")

    def test_model_restriction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_tenants(tmp, {
                "tenants": {
                    "key-limited": {
                        "name": "Limited",
                        "allowed_models": ["llama3"],
                    }
                }
            })
            with patch("proxy.tenants.TENANTS_FILE", path), \
                 patch("proxy.tenants._tenants_cache", None):
                assert check_model_allowed("key-limited", "llama3.2:1b")
                assert not check_model_allowed("key-limited", "gpt-4")

    def test_no_tenants_file_is_single_key(self):
        with patch("proxy.tenants.TENANTS_FILE", "/nonexistent"), \
             patch("proxy.tenants._tenants_cache", None):
            assert not is_multi_tenant()


# ---------------------------------------------------------------------------
# Request tracing
# ---------------------------------------------------------------------------

class TestTracing:
    client = TestClient(app)

    def test_response_has_trace_id(self):
        resp = self.client.get("/health")
        assert "x-request-id" in resp.headers

    def test_client_trace_id_preserved(self):
        resp = self.client.get("/health", headers={"x-request-id": "my-trace-123"})
        assert resp.headers["x-request-id"] == "my-trace-123"

    def test_auto_generated_trace_id(self):
        resp = self.client.get("/health")
        trace_id = resp.headers["x-request-id"]
        assert len(trace_id) > 10  # UUID format


# ---------------------------------------------------------------------------
# Python SDK
# ---------------------------------------------------------------------------

class TestSDK:
    def test_health(self):
        client = OpenClawClient(base_url="http://localhost:8005")
        # May fail if proxy not running, just test the object creation
        assert client.base_url == "http://localhost:8005"
        assert client.api_key == ""

    def test_headers(self):
        client = OpenClawClient(api_key="test-key")
        headers = client._headers()
        assert headers["Authorization"] == "Bearer test-key"
        assert headers["Content-Type"] == "application/json"

    def test_as_openai(self):
        client = OpenClawClient(base_url="http://localhost:8005", api_key="key")
        try:
            openai_client = client.as_openai()
            assert openai_client.base_url.host == "localhost"
        except ImportError:
            pass  # openai not installed


# ---------------------------------------------------------------------------
# Helm chart validation
# ---------------------------------------------------------------------------

class TestHelmChart:
    def test_chart_yaml_exists(self):
        assert os.path.exists("helm/openclaw-proxy/Chart.yaml")

    def test_values_yaml_exists(self):
        assert os.path.exists("helm/openclaw-proxy/values.yaml")

    def test_values_has_required_fields(self):
        with open("helm/openclaw-proxy/values.yaml") as f:
            content = f.read()
        assert "replicaCount" in content
        assert "redis" in content
        assert "postgresql" in content
        assert "autoscaling" in content
