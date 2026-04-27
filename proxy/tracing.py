"""Request tracing with correlation IDs.

Every request gets a unique trace ID (X-Request-Id header).
The trace ID is:
  - Added to response headers
  - Included in log entries
  - Passed to backend requests
  - Usable for distributed tracing (Jaeger, Datadog, etc.)
"""

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Use client-provided trace ID or generate one
        trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers["x-request-id"] = trace_id
        return response


def get_trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", str(uuid.uuid4()))
