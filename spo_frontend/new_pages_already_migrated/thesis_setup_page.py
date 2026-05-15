"""
Router: Thesis Setup page

Mount in main.py:

    from spo_frontend.new_pages_already_migrated.thesis_setup_page import router as thesis_setup_router
    app.include_router(thesis_setup_router)

Multi-thesis design note
------------------------
The backend stores one synopsis.json and a flat directory of chapter JSON files.
There is no native concept of multiple theses at the data layer.

The frontend implements multi-thesis scoping as follows:
  - A thesis index is persisted in browser localStorage (key: "spo_theses").
  - Each entry holds {id, title, author} derived from the imported synopsis.
  - The active thesis id is stored in localStorage (key: "spo_active_thesis").
  - Switching thesis calls the same backend endpoints — the backend always
    reflects the last-written synopsis/chapters state.

Full multi-thesis backend support (separate data namespaces per thesis) is a
future backend task. This router is unchanged when that work lands.
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


@router.get("/thesis-setup", response_class=HTMLResponse)
async def thesis_setup_page(request: Request):
    """
    Renders the Thesis Setup page.
    All data is fetched client-side:
      GET /thesis/synopsis    → Card 01 synopsis display
      GET /thesis/chapters    → Card 02 chapter list (then GET each for subtopics)
    """
    return templates.TemplateResponse(
        "thesis_setup.html",
        {"request": request, "api_base": _BACKEND},
    )
