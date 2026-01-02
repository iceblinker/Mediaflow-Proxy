import logging
import httpx
from typing import Optional
from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)

class HttpClientManager:
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """
        Returns the global singleton httpx.AsyncClient.
        Raises RuntimeError if the client has not been initialized.
        """
        if cls._client is None:
             # Lazy initialization if accessed before explicit startup (mostly for tests)
             logger.warning("Global HTTP client accessed before explicit initialization. Initializing now.")
             cls.start()
        return cls._client

    @classmethod
    def start(cls):
        """
        Initializes the global httpx.AsyncClient.
        Should be called on application startup.
        """
        if cls._client is not None:
            logger.warning("Global HTTP client already initialized.")
            return

        logger.info("Initializing global HTTP client with connection pooling...")
        mounts = settings.transport_config.get_mounts()
        
        # Configure client limits for connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=20, 
            max_connections=100, 
            keepalive_expiry=30.0
        )

        cls._client = httpx.AsyncClient(
            mounts=mounts,
            follow_redirects=True,
            timeout=settings.transport_config.timeout,
            limits=limits,
            verify=not settings.transport_config.disable_ssl_verification_globally
        )
        logger.info("Global HTTP client initialized.")

    @classmethod
    async def stop(cls):
        """
        Closes the global httpx.AsyncClient.
        Should be called on application shutdown.
        """
        if cls._client:
            logger.info("Closing global HTTP client...")
            await cls._client.aclose()
            cls._client = None
            logger.info("Global HTTP client closed.")
