"""Multi-tenancy: per-team API keys with own rate limits and budgets.

Tenants are configured in tenants.json:
{
  "tenants": {
    "team-alpha-key-xxx": {
      "name": "Team Alpha",
      "rate_limit_rpm": 100,
      "monthly_budget_usd": 500.0,
      "allowed_backends": ["openai", "ollama"],
      "allowed_models": ["gpt-4", "llama3.2:1b"]
    },
    "team-beta-key-yyy": {
      "name": "Team Beta",
      "rate_limit_rpm": 30,
      "monthly_budget_usd": 50.0
    }
  }
}

When tenants.json exists, it overrides the single PROXY_API_KEY.
Each tenant gets their own rate limit, budget, and backend restrictions.
"""

import json
import os

TENANTS_FILE = os.path.join(os.path.dirname(__file__), "..", "tenants.json")

_tenants_cache: dict | None = None


def _load_tenants() -> dict:
    global _tenants_cache
    if _tenants_cache is not None:
        return _tenants_cache
    if os.path.exists(TENANTS_FILE):
        with open(TENANTS_FILE) as f:
            _tenants_cache = json.load(f)
            return _tenants_cache
    return {}


def is_multi_tenant() -> bool:
    tenants = _load_tenants()
    return bool(tenants.get("tenants"))


def authenticate(api_key: str) -> dict | None:
    """Authenticate a tenant by API key.

    Returns tenant config dict if valid, None if not found.
    """
    tenants = _load_tenants()
    return tenants.get("tenants", {}).get(api_key)


def get_tenant_name(api_key: str) -> str | None:
    tenant = authenticate(api_key)
    return tenant.get("name") if tenant else None


def get_rate_limit(api_key: str) -> int | None:
    """Return per-tenant rate limit, or None to use global default."""
    tenant = authenticate(api_key)
    if tenant:
        return tenant.get("rate_limit_rpm")
    return None


def check_backend_allowed(api_key: str, backend_name: str) -> bool:
    """Return True if tenant is allowed to use this backend."""
    tenant = authenticate(api_key)
    if not tenant:
        return True
    allowed = tenant.get("allowed_backends")
    if allowed is None:
        return True
    return backend_name in allowed


def check_model_allowed(api_key: str, model: str | None) -> bool:
    """Return True if tenant is allowed to use this model."""
    if not model:
        return True
    tenant = authenticate(api_key)
    if not tenant:
        return True
    allowed = tenant.get("allowed_models")
    if allowed is None:
        return True
    return any(model.startswith(m) for m in allowed)


def get_monthly_budget(api_key: str) -> float | None:
    """Return per-tenant monthly budget, or None for unlimited."""
    tenant = authenticate(api_key)
    if tenant:
        return tenant.get("monthly_budget_usd")
    return None


def reload():
    """Force reload tenants from disk (for admin API)."""
    global _tenants_cache
    _tenants_cache = None
