"""
Router: Source Library page

Mount in main.py alongside the write_section router:

    from spo_frontend.new_pages_already_migrated.source_library_page import router as source_library_router
    app.include_router(source_library_router)

The page does a single server-side render with api_base injected.
All data (library, thesis folders) is fetched client-side via JS
to keep the page fast on load and avoid a blocking SSR payload.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "spo_frontend")
templates    = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

_BACKEND = os.environ.get("SPO_API_URL", "http://localhost:8000")


@router.get("/source-library", response_class=HTMLResponse)
async def source_library_page(request: Request):
    """
    Renders the Source Library page.
    api_base is injected so client JS knows where to call.
    All dynamic data is fetched client-side:
      - GET /sources/library-view  → Card 03 group list
      - GET /drive/local-files     → Card 02 thesis folder list
    """
    return templates.TemplateResponse(
        "source_library.html",
        {"request": request, "api_base": _BACKEND},
    )
