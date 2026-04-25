import json
import os

BACKENDS_FILE = os.path.join(os.path.dirname(__file__), "..", "backends.json")

# Default: everything goes to Ollama
_DEFAULT_BACKENDS = {
    "default": {
        "url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "name": "ollama",
    },
}


def _load_backends() -> dict:
    if os.path.exists(BACKENDS_FILE):
        with open(BACKENDS_FILE) as f:
            return json.load(f)
    return {}


def resolve(model: str | None, path: str) -> tuple[str, str]:
    """Given a model name and path, return (backend_url, backend_name).

    Matches model prefix against configured backends.
    Falls back to the default backend.
    """
    backends = _load_backends()
    default = backends.get("default", _DEFAULT_BACKENDS["default"])
    routes = backends.get("routes", {})

    if model:
        for prefix, backend in routes.items():
            if model.startswith(prefix):
                return backend["url"], backend.get("name", prefix)

    return default["url"], default.get("name", "ollama")
