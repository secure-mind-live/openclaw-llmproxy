import json
import os
import tempfile
from unittest.mock import patch

import httpx

from proxy.fallback import get_fallback_chain, is_fallback_eligible


class TestFallbackEligibility:
    def test_timeout_is_eligible(self):
        assert is_fallback_eligible(exc=httpx.TimeoutException("timeout"))

    def test_connect_error_is_eligible(self):
        assert is_fallback_eligible(exc=httpx.ConnectError("refused"))

    def test_500_is_eligible(self):
        assert is_fallback_eligible(status_code=500)

    def test_502_is_eligible(self):
        assert is_fallback_eligible(status_code=502)

    def test_429_is_not_eligible(self):
        assert not is_fallback_eligible(status_code=429)

    def test_401_is_not_eligible(self):
        assert not is_fallback_eligible(status_code=401)

    def test_200_is_not_eligible(self):
        assert not is_fallback_eligible(status_code=200)


class TestFallbackChain:
    def _write_backends(self, tmp, data):
        path = os.path.join(tmp, "backends.json")
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def test_no_fallback_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_backends(tmp, {
                "default": {"url": "http://localhost:11434", "name": "ollama"},
                "routes": {
                    "gpt-": {"url": "https://api.openai.com", "name": "openai", "timeout_s": 30}
                },
            })
            with patch("proxy.router.BACKENDS_FILE", path):
                chain = get_fallback_chain("openai")
                assert chain == []

    def test_fallback_chain_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_backends(tmp, {
                "default": {"url": "http://localhost:11434", "name": "ollama", "timeout_s": 60},
                "routes": {
                    "gpt-": {"url": "https://api.openai.com", "name": "openai", "timeout_s": 30, "fallback": ["ollama"]},
                },
            })
            with patch("proxy.router.BACKENDS_FILE", path):
                chain = get_fallback_chain("openai")
                assert len(chain) == 1
                assert chain[0]["name"] == "ollama"
                assert chain[0]["url"] == "http://localhost:11434"
