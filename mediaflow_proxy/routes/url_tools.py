import asyncio
from fastapi import APIRouter, HTTPException, Depends
from mediaflow_proxy.schemas import GenerateUrlRequest, GenerateMultiUrlRequest, MultiUrlRequestItem
from mediaflow_proxy.utils.crypto_utils import EncryptionHandler
from mediaflow_proxy.utils.http_utils import encode_mediaflow_proxy_url
from mediaflow_proxy.utils.base64_utils import encode_url_to_base64, decode_base64_url, is_base64_url

router = APIRouter()


@router.post(
    "/generate_encrypted_or_encoded_url",
    description="Generate a single encoded URL",
    response_description="Returns a single encoded URL",
    deprecated=True,
)
async def generate_encrypted_or_encoded_url(
    request: GenerateUrlRequest,
):
    """
    Generate a single encoded URL based on the provided request.
    """
    return {"encoded_url": (await generate_url(request))["url"]}


@router.post(
    "/generate_url",
    description="Generate a single encoded URL",
    response_description="Returns a single encoded URL",
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
        encryption_handler=encryption_handler,
        expiration=request.expiration,
        ip=ip_str,
        filename=request.filename,
    )

    return {"url": encoded_url}


@router.post(
    "/generate_urls",
    description="Generate multiple encoded URLs with shared common parameters",
    response_description="Returns a list of encoded URLs",
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
            encryption_handler=encryption_handler,
            expiration=request.expiration,
            ip=ip_str,
            filename=url_item.filename,
        )

    tasks = [_process_url_item(url_item) for url_item in request.urls]
    encoded_urls = await asyncio.gather(*tasks)
    return {"urls": encoded_urls}


@router.post(
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


@router.post(
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


@router.get(
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
