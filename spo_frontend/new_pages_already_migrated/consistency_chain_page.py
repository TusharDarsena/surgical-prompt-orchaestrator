"""
Router: Consistency Chain page

Mount in main.py:
    import spo_frontend.new_pages_already_migrated.consistency_chain_page as _mod_cc
    _mod_cc.templates = _templates
    app.include_router(_mod_cc.router)
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import os

router = APIRouter()

# Path resolved at import time — patched by main.py to use the shared instance
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "spo_frontend")
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))

_BACKEND = os.environ.get("SPO_API_URL", "http://localhost:8000")


@router.get("/consistency-chain", response_class=HTMLResponse)
async def consistency_chain_page(request: Request):
    """
    Serves the Consistency Chain Jinja2 page.
    All data (chapters, chain, subtopics) is fetched client-side.
    """
    return templates.TemplateResponse(
        request=request,
        name="consistency_chain.html",
        context={
            "request": request,
            "api_base": _BACKEND,
            "active_page": "consistency-chain",
        },
    )
