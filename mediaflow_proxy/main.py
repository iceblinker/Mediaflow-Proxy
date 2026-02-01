import logging
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI, Depends
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from mediaflow_proxy.configs import settings
from mediaflow_proxy.middleware import UIAccessControlMiddleware
from mediaflow_proxy.routes import (
    proxy_router,
    extractor_router,
    speedtest_router,
    playlist_builder_router,
    xtream_root_router,
    acestream_router,
)
from mediaflow_proxy.routes.general import router as general_router
from mediaflow_proxy.routes.url_tools import router as url_tools_router
from mediaflow_proxy.routes.diagnostics import router as diagnostics_router
from mediaflow_proxy.routes.ai_playlist import router as ai_playlist_router
from mediaflow_proxy.schemas import GenerateUrlRequest, GenerateMultiUrlRequest, MultiUrlRequestItem
from mediaflow_proxy.utils.cache_utils import EXTRACTOR_CACHE
from mediaflow_proxy.utils.crypto_utils import EncryptionHandler, EncryptionMiddleware
from mediaflow_proxy.utils.http_utils import encode_mediaflow_proxy_url
from mediaflow_proxy.utils.base64_utils import encode_url_to_base64, decode_base64_url, is_base64_url
from mediaflow_proxy.utils.error_handler import register_exception_handlers
from mediaflow_proxy.utils.security import verify_api_key
from mediaflow_proxy.utils.acestream import acestream_manager

logging.basicConfig(level=settings.log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    if settings.clear_cache_on_startup:
        logger.info("Clearing caches on startup (CLEAR_CACHE_ON_STARTUP=true)")
        EXTRACTOR_CACHE.clear()
        logger.info("Extractor cache cleared")

    yield

    # Shutdown
    logger.info("Shutting down...")
    # Close acestream sessions
    await acestream_manager.close()
    logger.info("Acestream manager closed")


app = FastAPI(lifespan=lifespan)
from fastapi.security import APIKeyQuery, APIKeyHeader
from fastapi import HTTPException
import asyncio
from starlette.responses import RedirectResponse

api_password_query = APIKeyQuery(name="api_password", auto_error=False)
api_password_header = APIKeyHeader(name="api_password", auto_error=False)
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


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/favicon.ico")
async def get_favicon():
    return RedirectResponse(url="/logo.png")


@app.get("/speedtest")
async def show_speedtest_page():
    return RedirectResponse(url="/speedtest.html")


@app.get("/url-generator")
async def show_url_generator_page():
    return RedirectResponse(url="/url_generator.html")


@app.post(
    "/generate_encrypted_or_encoded_url",
    description="Generate a single encoded URL",
    response_description="Returns a single encoded URL",
    deprecated=True,
    tags=["url"],
)
async def generate_encrypted_or_encoded_url(
    request: GenerateUrlRequest,
):
    """
    Generate a single encoded URL based on the provided request.
    """
    return {"encoded_url": (await generate_url(request))["url"]}


@app.post(
    "/generate_url",
    description="Generate a single encoded URL",
    response_description="Returns a single encoded URL",
    tags=["url"],
)
async def generate_url(request: GenerateUrlRequest):
    """Generate a single encoded URL based on the provided request."""
    encryption_handler = EncryptionHandler(request.api_password) if request.api_password else None

    # Ensure api_password is in query_params if provided
    query_params = request.query_params.copy()
    if "api_password" not in query_params and request.api_password:
        query_params["api_password"] = request.api_password

    # Convert IP to string if provided
    ip_str = str(request.ip) if request.ip else None

    # Handle base64 encoding of destination URL if requested
    destination_url = request.destination_url
    if request.base64_encode_destination and destination_url:
        destination_url = encode_url_to_base64(destination_url)

    encoded_url = encode_mediaflow_proxy_url(
        mediaflow_proxy_url=request.mediaflow_proxy_url,
        endpoint=request.endpoint,
        destination_url=destination_url,
        query_params=query_params,
        request_headers=request.request_headers,
        response_headers=request.response_headers,
        propagate_response_headers=request.propagate_response_headers,
        remove_response_headers=request.remove_response_headers,
        encryption_handler=encryption_handler,
        expiration=request.expiration,
        ip=ip_str,
        filename=request.filename,
    )

    return {"url": encoded_url}


@app.post(
    "/generate_urls",
    description="Generate multiple encoded URLs with shared common parameters",
    response_description="Returns a list of encoded URLs",
    tags=["url"],
)
async def generate_urls(request: GenerateMultiUrlRequest):
    """Generate multiple encoded URLs with shared common parameters."""
    # Set up encryption handler if password is provided
    encryption_handler = EncryptionHandler(request.api_password) if request.api_password else None

    # Convert IP to string if provided
    ip_str = str(request.ip) if request.ip else None

    async def _process_url_item(
        url_item: MultiUrlRequestItem,
    ) -> str:
        """Process a single URL item with common parameters and return the encoded URL."""
        query_params = url_item.query_params.copy()
        if "api_password" not in query_params and request.api_password:
            query_params["api_password"] = request.api_password

        # Generate the encoded URL
        return encode_mediaflow_proxy_url(
            mediaflow_proxy_url=request.mediaflow_proxy_url,
            endpoint=url_item.endpoint,
            destination_url=url_item.destination_url,
            query_params=query_params,
            request_headers=url_item.request_headers,
            response_headers=url_item.response_headers,
            propagate_response_headers=url_item.propagate_response_headers,
            remove_response_headers=url_item.remove_response_headers,
            encryption_handler=encryption_handler,
            expiration=request.expiration,
            ip=ip_str,
            filename=url_item.filename,
        )

    tasks = [_process_url_item(url_item) for url_item in request.urls]
    encoded_urls = await asyncio.gather(*tasks)
    return {"urls": encoded_urls}


@app.post(
    "/base64/encode",
    description="Encode a URL to base64 format",
    response_description="Returns the base64 encoded URL",
    tags=["base64"],
)
async def encode_url_base64(url: str):
    """
    Encode a URL to base64 format.

    Args:
        url (str): The URL to encode.

    Returns:
        dict: A dictionary containing the encoded URL.
    """
    try:
        encoded_url = encode_url_to_base64(url)
        return {"encoded_url": encoded_url, "original_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to encode URL: {str(e)}")


@app.post(
    "/base64/decode",
    description="Decode a base64 encoded URL",
    response_description="Returns the decoded URL",
    tags=["base64"],
)
async def decode_url_base64(encoded_url: str):
    """
    Decode a base64 encoded URL.

    Args:
        encoded_url (str): The base64 encoded URL to decode.

    Returns:
        dict: A dictionary containing the decoded URL.
    """
    decoded_url = decode_base64_url(encoded_url)
    if decoded_url is None:
        raise HTTPException(status_code=400, detail="Invalid base64 encoded URL")

    return {"decoded_url": decoded_url, "encoded_url": encoded_url}


@app.get(
    "/base64/check",
    description="Check if a string appears to be a base64 encoded URL",
    response_description="Returns whether the string is likely base64 encoded",
    tags=["base64"],
)
async def check_base64_url(url: str):
    """
    Check if a string appears to be a base64 encoded URL.

    Args:
        url (str): The string to check.

    Returns:
        dict: A dictionary indicating if the string is likely base64 encoded.
    """
    is_base64 = is_base64_url(url)
    result = {"url": url, "is_base64": is_base64}

    if is_base64:
        decoded_url = decode_base64_url(url)
        if decoded_url:
            result["decoded_url"] = decoded_url

    return result


app.include_router(diagnostics_router, prefix="/v1", tags=["diagnostics"])
app.include_router(ai_playlist_router, prefix="/v1/playlist", tags=["ai_playlist"])

app.include_router(proxy_router, prefix="/proxy", tags=["proxy"], dependencies=[Depends(verify_api_key)])
app.include_router(acestream_router, prefix="/proxy", tags=["acestream"], dependencies=[Depends(verify_api_key)])
app.include_router(extractor_router, prefix="/extractor", tags=["extractors"], dependencies=[Depends(verify_api_key)])
app.include_router(speedtest_router, prefix="/speedtest", tags=["speedtest"], dependencies=[Depends(verify_api_key)])
app.include_router(playlist_builder_router, prefix="/playlist", tags=["playlist"])
app.include_router(xtream_root_router, tags=["xtream"])

# Static Files
from starlette.responses import HTMLResponse

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
