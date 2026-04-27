import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from proxy import tenants

PROXY_API_KEY = os.getenv("PROXY_API_KEY", "")
EXEMPT_PATHS = {"/health", "/dashboard", "/dashboard/metrics", "/metrics"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

        # Multi-tenant mode
        if tenants.is_multi_tenant():
            tenant = tenants.authenticate(token)
            if not tenant:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or missing API key"},
                )
            request.state.tenant = tenant
            request.state.tenant_key = token
            return await call_next(request)

        # Single-key mode
        if not PROXY_API_KEY:
            return await call_next(request)

        if auth_header != f"Bearer {PROXY_API_KEY}":
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing Authorization header"},
            )

        return await call_next(request)
