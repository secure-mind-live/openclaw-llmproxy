import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

PROXY_API_KEY = os.getenv("PROXY_API_KEY", "")
EXEMPT_PATHS = {"/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not PROXY_API_KEY:
            return await call_next(request)

        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header != f"Bearer {PROXY_API_KEY}":
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing Authorization header"},
            )

        return await call_next(request)
