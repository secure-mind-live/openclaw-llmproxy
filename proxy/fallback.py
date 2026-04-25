import httpx

from proxy.router import _load_backends


def get_fallback_chain(backend_name: str) -> list[dict]:
    """Return list of fallback backend configs for the given backend."""
    backends = _load_backends()
    routes = backends.get("routes", {})
    default = backends.get("default", {})

    # Find the route that matched this backend
    matched_route = None
    for _prefix, route in routes.items():
        if route.get("name") == backend_name:
            matched_route = route
            break

    if not matched_route:
        return []

    fallback_names = matched_route.get("fallback", [])
    if not fallback_names:
        return []

    chain = []
    for name in fallback_names:
        # Look up by name in routes
        for _prefix, route in routes.items():
            if route.get("name") == name:
                chain.append({
                    "url": route.get("urls", [route["url"]])[0] if "urls" in route else route["url"],
                    "name": name,
                    "timeout_s": route.get("timeout_s", 30),
                })
                break
        else:
            # Check default
            if default.get("name") == name:
                chain.append({
                    "url": default["url"],
                    "name": name,
                    "timeout_s": default.get("timeout_s", 60),
                })

    return chain


def is_fallback_eligible(status_code: int | None = None, exc: Exception | None = None) -> bool:
    """Return True if the failure should trigger a fallback attempt."""
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError))
    if status_code is not None:
        return status_code >= 500
    return False
