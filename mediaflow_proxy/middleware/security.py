from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all responses.
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        
        # Strict-Transport-Security: (HSTS)
        # Max age: 1 year (31536000 seconds), include subdomains
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # X-Frame-Options
        response.headers["X-Frame-Options"] = "DENY"
        
        # Referrer-Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Content-Security-Policy (CSP)
        # This is a strict policy; might need adjustment if external scripts are used.
        # For an API/Proxy, 'default-src 'none'' or 'self' is often appropriate.
        # Since we serve a static UI, we need 'self' and potentially 'unsafe-inline' for some frameworks if not built cleanly.
        # Allowing 'self' for now.
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';"

        return response
