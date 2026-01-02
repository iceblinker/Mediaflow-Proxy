import logging
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any
from mediaflow_proxy.configs import settings

logger = logging.getLogger(__name__)

router = APIRouter()

class DiagnosticRequest(BaseModel):
    url: HttpUrl
    method: str = "HEAD"
    headers: Optional[Dict[str, str]] = None

class DiagnosticResponse(BaseModel):
    url: str
    status_code: Optional[int] = None
    headers: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    ai_analysis: Optional[str] = None

async def query_ollama(prompt: str) -> str:
    """
    Sends a prompt to the configured Ollama instance and returns the response.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.ollama_host}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "stream": False
                }
            )
            response.raise_for_status()
            result = response.json()
            return result.get("response", "No response from AI model.")
    except Exception as e:
        logger.error(f"Failed to query Ollama: {e}")
        return f"AI Analysis Failed: {str(e)}"

@router.post("/diagnose", response_model=DiagnosticResponse)
async def diagnose_stream(request: DiagnosticRequest):
    """
    Diagnoses a stream URL by attempting to connect and then asking AI to analyze the result.
    """
    url_str = str(request.url)
    result = DiagnosticResponse(url=url_str)
    
    # 1. Fetch the URL to gather diagnostics
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=15.0) as client:
            response = await client.request(
                method=request.method,
                url=url_str,
                headers=request.headers
            )
            result.status_code = response.status_code
            result.headers = dict(response.headers)
            
            # If successful (2xx), mostly just report success, but maybe user is curious about headers
            if response.is_success:
                prompt_context = f"The stream URL {url_str} is accessible (HTTP {result.status_code}).\nHeaders: {result.headers}"
            else:
                prompt_context = f"The stream URL {url_str} failed with HTTP {result.status_code}.\nHeaders: {result.headers}"
                
    except httpx.RequestError as e:
        result.error = str(e)
        prompt_context = f"Connection to {url_str} failed completely.\nError: {str(e)}"
    
    # 2. Ask AI for analysis
    prompt = (
        f"You are a video streaming expert debugging a media proxy issue.\n"
        f"Analyze the following diagnostics for a video stream:\n\n"
        f"{prompt_context}\n\n"
        f"Provide a concise, plain-English explanation of what might be wrong (or if it's working) and suggest a fix if applicable."
    )
    
    result.ai_analysis = await query_ollama(prompt)
    
    return result
