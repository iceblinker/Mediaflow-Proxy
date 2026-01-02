import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_base64_encode_decode(client: AsyncClient):
    """
    Test base64 encoding and decoding.
    """
    original_url = "https://example.com/video.mp4"
    
    # Encode
    response_encode = await client.post("/base64/encode", params={"url": original_url})
    assert response_encode.status_code == 200
    encoded_data = response_encode.json()
    assert encoded_data["original_url"] == original_url
    assert "encoded_url" in encoded_data
    encoded_url = encoded_data["encoded_url"]

    # Decode
    response_decode = await client.post("/base64/decode", params={"encoded_url": encoded_url})
    assert response_decode.status_code == 200
    decoded_data = response_decode.json()
    assert decoded_data["decoded_url"] == original_url

@pytest.mark.asyncio
async def test_base64_check(client: AsyncClient):
    """
    Test base64 check endpoint.
    """
    # Test valid
    response = await client.get("/base64/check", params={"url": "aHR0cHM6Ly9leGFtcGxlLmNvbQ=="}) # https://example.com
    assert response.status_code == 200
    assert response.json()["is_base64"] is True
    
    # Test invalid
    response = await client.get("/base64/check", params={"url": "not-base64!"})
    assert response.status_code == 200
    assert response.json()["is_base64"] is False
