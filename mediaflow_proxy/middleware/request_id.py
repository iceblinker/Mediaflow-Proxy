import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_CTX_KEY = "request_id"
_request_id_ctx_var: ContextVar[str] = ContextVar(REQUEST_ID_CTX_KEY, default=None)

def get_request_id() -> str:
    """Get the current request ID from context."""
    return _request_id_ctx_var.get()

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        _request_id_ctx_var.set(request_id)
        
        response = await call_next(request)
        
        response.headers["X-Request-ID"] = request_id
        return response
