import logging
import json
import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from mediaflow_proxy.configs import settings
from mediaflow_proxy.utils.http_utils import get_original_scheme

logger = logging.getLogger(__name__)

router = APIRouter()

async def query_ollama_json(prompt: str) -> dict:
    """
    Sends a prompt to Ollama and expects a JSON response.
    """
    system_prompt = (
        "You are a movie and TV show expert tailored for Stremio and Torrent users. "
        "Return ONLY a JSON array of objects. "
        "Each object must have 'title' (string) and 'year' (string or int). "
        "Prioritize popular, highly-seeded content that is likely to be available on public torrent trackers. "
        "Do not include any other text."
    )
    
    full_prompt = f"{system_prompt}\n\nUser request: {prompt}"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.ollama_host}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": full_prompt,
                    "format": "json", # Force JSON output if model supports it
                    "stream": False
                }
            )
            response.raise_for_status()
            result = response.json()
            
            # Parse the response text as JSON
            content = result.get("response", "[]")
            return json.loads(content)
            
    except Exception as e:
        logger.error(f"Failed to query Ollama for playlist: {e}")
        return []

@router.get("/ai", response_class=Response)
async def generate_ai_playlist(
    request: Request,
    prompt: str = Query(..., description="Description of the playlist you want (e.g., '80s action movies')")
):
    """
    Generates an m3u8 playlist based on a natural language prompt using AI.
    The items in the playlist are lazy-resolved via a placeholder endpoint.
    """
    items = await query_ollama_json(prompt)
    
    if not items:
        # Fallback/Empty response
        return Response(
            content="#EXTM3U\n#EXTINF:-1,No results found from AI\nhttp://localhost/error.mp4",
            media_type="application/vnd.apple.mpegurl"
        )
    
    # Construct base URL for lazy resolution
    original_scheme = get_original_scheme(request)
    base_url = f"{original_scheme}://{request.url.netloc}"
    
    lines = ["#EXTM3U"]
    
    for item in items:
        title = item.get("title", "Unknown Title")
        year = item.get("year", "")
        
        display_title = f"{title} ({year})" if year else title
        
        # Encode query for the resolving endpoint
        # For MVP, we just point to a valid-looking URL structure or a resolver if we had one
        # Here we will assume we can't fully implement 'resolve' without a real addon logic,
        # so we will point to a place that *would* be the resolver.
        # Since we don't have a generic '/resolve' endpoint yet, let's create a placeholder structure.
        # Ideally, this would link to: /v1/playlist/resolve?q={title}
        
        query_param = f"{title} {year}".strip()
        encoded_query = httpx.URL(query_param).path # minimal encoding
        
        lines.append(f"#EXTINF:-1 group-title=\"AI Generated\",{display_title}")
        # Note: In a real implementation, this URL needs to actually function. 
        # For now, we will point it to a non-existent resolver to demonstrate the concept,
        # or we could point it to a 'search' endpoint if one existed.
        lines.append(f"{base_url}/v1/playlist/resolve?q={query_param}")
        
    content = "\n".join(lines)
    
    return Response(
        content=content,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="ai_playlist.m3u"',
        }
    )

@router.get("/resolve")
async def resolve_stream(q: str = Query(...)):
    """
    Placeholder/MVP endpoint to resolve a query to a stream.
    In a full implementation, this would query the Stremio Addon.
    """
    # MVP: Just return a mock redirect or error to show connectivity
    # Real world: Query Stremio Addon -> Get Stream -> 302 Redirect
    logger.info(f"Resolving query: {q}")
    raise HTTPException(status_code=501, detail=f"Lazy resolution for '{q}' is not yet implemented. This would be the step where we call valid stremio addons.")
