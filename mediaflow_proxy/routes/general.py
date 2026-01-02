from fastapi import APIRouter
from starlette.responses import RedirectResponse

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "healthy"}


@router.get("/favicon.ico")
async def get_favicon():
    return RedirectResponse(url="/static/logo.png")
