"""
Router: Write Section page

Mount in main.py:
    from routers.write_section import router as write_section_router
    app.include_router(write_section_router)
    app.mount("/static", StaticFiles(directory="static"), name="static")
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import httpx
import os

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_BACKEND = os.environ.get("SPO_API_URL", "http://localhost:8000")


@router.get("/write-section", response_class=HTMLResponse)
async def write_section_page(request: Request):
    """
    Server-renders chapter options for instant first paint.
    All dynamic data (subtopics, run states, drafts) is fetched client-side.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{_BACKEND}/thesis/chapters")
            chapters = r.json() if r.status_code == 200 else []
    except Exception:
        chapters = []

    return templates.TemplateResponse(
        "write_section.html",
        {"request": request, "chapters": chapters, "api_base": _BACKEND},
    )
