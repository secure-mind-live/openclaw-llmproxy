import os
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "60"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_key(self, request: Request) -> str:
        return request.client.host if request.client else "__unknown__"

    def _is_rate_limited(self, key: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        self._requests[key] = [t for t in self._requests[key] if t > window_start]
        if len(self._requests[key]) >= RATE_LIMIT_RPM:
            return True
        self._requests[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next):
        if RATE_LIMIT_RPM <= 0:
            return await call_next(request)

        if request.url.path == "/health":
            return await call_next(request)

        key = self._get_key(request)
        if self._is_rate_limited(key):
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
