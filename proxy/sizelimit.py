import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

MAX_REQUEST_SIZE_MB = float(os.getenv("MAX_REQUEST_SIZE_MB", "10"))


class SizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        max_bytes = int(MAX_REQUEST_SIZE_MB * 1024 * 1024)
        content_length = request.headers.get("content-length")

        if content_length and int(content_length) > max_bytes:
            return JSONResponse(
                status_code=413,
                content={"error": f"Request body exceeds {MAX_REQUEST_SIZE_MB}MB limit"},
            )

        body = await request.body()
        if len(body) > max_bytes:
            return JSONResponse(
                status_code=413,
                content={"error": f"Request body exceeds {MAX_REQUEST_SIZE_MB}MB limit"},
            )

        return await call_next(request)
