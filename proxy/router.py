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


def _pick_url_from_backend(backend: dict, name: str) -> str:
    """Pick a URL from a backend config, using load balancer if multiple URLs."""
    urls = backend.get("urls")
    if urls and len(urls) > 1:
        from proxy.loadbalancer import pick_url
        strategy = backend.get("strategy", "round_robin")
        return pick_url(name, urls, strategy)
    if urls:
        return urls[0]
    return backend["url"]


def resolve(model: str | None, path: str) -> tuple[str, str]:
    """Given a model name and path, return (backend_url, backend_name).

    Matches model prefix against configured backends.
    Falls back to the default backend.
    Supports load balancing via 'urls' array in backend config.
    """
    backends = _load_backends()
    default = backends.get("default", _DEFAULT_BACKENDS["default"])
    routes = backends.get("routes", {})

    if model:
        for prefix, backend in routes.items():
            if model.startswith(prefix):
                name = backend.get("name", prefix)
                url = _pick_url_from_backend(backend, name)
                return url, name

    name = default.get("name", "ollama")
    url = _pick_url_from_backend(default, name)
    return url, name
