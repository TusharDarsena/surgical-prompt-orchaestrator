"""
Router: App Home page

Mount in main.py:

    from spo_frontend.new_pages_already_migrated.app_home_page import router as app_home_router
    app.include_router(app_home_router)

Serves /app as the main dashboard.
All data (synopsis, chapters, source counts, drive status) is fetched
client-side — this route only renders the shell HTML.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "spo_frontend")
templates    = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

_BACKEND = os.environ.get("SPO_API_URL", "http://localhost:8000")


@router.get("/app", response_class=HTMLResponse)
async def app_home(request: Request):
    return templates.TemplateResponse(
        "app_home.html",
        {"request": request, "api_base": _BACKEND},
    )


@router.get("/", response_class=RedirectResponse, include_in_schema=False)
async def root_redirect():
    """Redirect bare root to /app so the existing GET / health endpoint
    in main.py is not displaced — add this only if you want / → /app."""
    return RedirectResponse(url="/app")
