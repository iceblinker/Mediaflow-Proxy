import logging
from importlib import resources

from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from mediaflow_proxy.configs import settings
from mediaflow_proxy.middleware import UIAccessControlMiddleware
from mediaflow_proxy.routes import proxy_router, extractor_router, speedtest_router, playlist_builder_router
from mediaflow_proxy.routes.general import router as general_router
from mediaflow_proxy.routes.url_tools import router as url_tools_router
from mediaflow_proxy.utils.crypto_utils import EncryptionMiddleware
from mediaflow_proxy.utils.logging_utils import setup_logging
from mediaflow_proxy.utils.error_handler import register_exception_handlers
from mediaflow_proxy.utils.security import verify_api_key

from contextlib import asynccontextmanager
from mediaflow_proxy.utils.http_client import HttpClientManager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    HttpClientManager.start()
    logger.info("--- STARTUP: Registered Routes ---")
    for route in app.routes:
        logger.info(f"Route: {route.path} | Name: {route.name}")
    logger.info("----------------------------------")
    yield
    # Shutdown
    await HttpClientManager.stop()


app = FastAPI(lifespan=lifespan)

from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)

from mediaflow_proxy.middleware.request_id import RequestIdMiddleware
from mediaflow_proxy.middleware.security import SecurityHeadersMiddleware
from mediaflow_proxy.middleware.rate_limiter import RateLimitMiddleware

# Middleware
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(EncryptionMiddleware)
app.add_middleware(UIAccessControlMiddleware)

# Error handlers
register_exception_handlers(app)

# Routers
app.include_router(general_router)
app.include_router(url_tools_router)

from mediaflow_proxy.routes.diagnostics import router as diagnostics_router
from mediaflow_proxy.routes.ai_playlist import router as ai_playlist_router

app.include_router(diagnostics_router, prefix="/v1", tags=["diagnostics"])
app.include_router(ai_playlist_router, prefix="/v1/playlist", tags=["ai_playlist"])

app.include_router(proxy_router, prefix="/proxy", tags=["proxy"], dependencies=[Depends(verify_api_key)])
app.include_router(extractor_router, prefix="/extractor", tags=["extractors"], dependencies=[Depends(verify_api_key)])
app.include_router(speedtest_router, prefix="/speedtest", tags=["speedtest"], dependencies=[Depends(verify_api_key)])
app.include_router(playlist_builder_router, prefix="/playlist", tags=["playlist"])

# Static Files
from starlette.responses import RedirectResponse, HTMLResponse

# Static Files
static_path = resources.files("mediaflow_proxy").joinpath("static")
app.mount("/static", StaticFiles(directory=str(static_path), html=True), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    return '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0; url=/static/index.html" /></head><body>Redirecting to <a href="/static/index.html">UI</a>...</body></html>'


def run():
    import uvicorn

    uvicorn.run("mediaflow_proxy.main:app", host="0.0.0.0", port=8888, log_level=settings.log_level.lower(), workers=settings.workers)


if __name__ == "__main__":
    run()
