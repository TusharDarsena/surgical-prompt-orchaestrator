"""
SPO Backend — Surgical Prompt Orchestrator v0.5.0

Run from the PROJECT ROOT (the folder containing both spo_backend/ and spo_frontend/):
    uvicorn spo_backend.main:app --reload --port 8000

Do NOT run from inside spo_backend/ — spo_frontend won't be importable.
"""

# ── Windows asyncio fix — must be FIRST, before any asyncio import ────────────
import sys
import os

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Ensure both spo_backend/ and project root are on sys.path ─────────────────
# This file lives at <root>/spo_backend/main.py
_THIS_FILE    = os.path.abspath(__file__)
_BACKEND_DIR  = os.path.dirname(_THIS_FILE)        # .../spo_backend/
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)      # .../ (project root)

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)   # makes `from routers import ...` work
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)  # makes `from spo_frontend import ...` work

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Paths — computed once, used everywhere ────────────────────────────────────
BASE_DIR      = _BACKEND_DIR
FRONTEND_DIR  = os.path.join(_PROJECT_ROOT, "spo_frontend")
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR    = os.path.join(FRONTEND_DIR, "static")

# ── Single shared Jinja2Templates instance ────────────────────────────────────
# Built here with the correct path. Patched onto each page router module below
# AFTER import, overwriting whatever broken path each router computed itself.
_templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ── Backend routers ───────────────────────────────────────────────────────────
from routers import thesis, sources, consistency, notes, compiler, importer, drive, sections
from routers import notebooklm

# ── Frontend page router modules ──────────────────────────────────────────────
import spo_frontend.new_pages_already_migrated.app_home_page       as _mod_app_home
import spo_frontend.new_pages_already_migrated.thesis_setup_page   as _mod_thesis
import spo_frontend.new_pages_already_migrated.source_library_page as _mod_sources
import spo_frontend.new_pages_already_migrated.write_section       as _mod_write

# ── Patch the broken templates reference on every page router ─────────────────
# Each router file computes FRONTEND_DIR from its own __file__ which resolves
# to spo_frontend/spo_frontend/templates when running from the project root.
# Overwriting the module-level `templates` variable fixes this without touching
# any of the router files themselves.
_mod_app_home.templates = _templates
_mod_thesis.templates   = _templates
_mod_sources.templates  = _templates
_mod_write.templates    = _templates

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SPO — Surgical Prompt Orchestrator",
    description=(
        "Prompt stitching engine for academic writing. "
        "v0.4: Chapterization JSON → NotebookLM prompt directly. "
        "Bulk chapterization import. Source guidance per subtopic. "
        "v0.5: NotebookLM automation via notebooklm-py."
    ),
    version="0.5.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register backend routers ──────────────────────────────────────────────────
app.include_router(thesis.router)
app.include_router(sources.router)
app.include_router(consistency.router)
app.include_router(notes.router)
app.include_router(compiler.router)
app.include_router(importer.router)
app.include_router(drive.router)
app.include_router(sections.router)
app.include_router(notebooklm.router)

# ── Register frontend page routers ────────────────────────────────────────────
app.include_router(_mod_app_home.router)   # GET /app
app.include_router(_mod_thesis.router)     # GET /thesis-setup
app.include_router(_mod_sources.router)    # GET /source-library
app.include_router(_mod_write.router)      # GET /write-section

# ── Serve static files ────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health():
    from services.storage import DATA_DIR
    return {
        "status": "running",
        "version": "0.5.0",
        "data_dir": str(DATA_DIR),
        "docs":     "http://localhost:8000/docs",
    }