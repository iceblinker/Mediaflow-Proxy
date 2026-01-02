from fastapi import Security, HTTPException
from fastapi.security import APIKeyQuery, APIKeyHeader
from mediaflow_proxy.configs import settings

api_password_query = APIKeyQuery(name="api_password", auto_error=False)
api_password_header = APIKeyHeader(name="api_password", auto_error=False)

async def verify_api_key(api_key: str = Security(api_password_query), api_key_alt: str = Security(api_password_header)):
    """
    Verifies the API key for the request.

    Args:
        api_key (str): The API key to validate.
        api_key_alt (str): The alternative API key to validate.

    Raises:
        HTTPException: If the API key is invalid.
    """
    if not settings.api_password:
        return

    if api_key == settings.api_password or api_key_alt == settings.api_password:
        return

    raise HTTPException(status_code=403, detail="Could not validate credentials")
