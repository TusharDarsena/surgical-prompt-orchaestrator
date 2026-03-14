"""
SPO Backend — Surgical Prompt Orchestrator v0.4.0
Run from the spo_backend directory:
    uvicorn main:app --reload --port 8000
"""

# ── Windows asyncio fix — must be FIRST, before any asyncio import ────────────
import sys
import os

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # walks up from spo_backend/ to find .env at project root

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Paths to frontend static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "spo_frontend")

from routers import thesis, sources, consistency, notes, compiler, importer, drive, sections
from routers import notebooklm
from spo_frontend.new_pages.write_section import router as write_section_router

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

app.include_router(thesis.router)
app.include_router(sources.router)
app.include_router(consistency.router)
app.include_router(notes.router)
app.include_router(compiler.router)
app.include_router(importer.router)
app.include_router(drive.router)
app.include_router(sections.router)
app.include_router(notebooklm.router)
app.include_router(write_section_router)

# Frontend static files (HTML/CSS/JS)
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.get("/", tags=["Health"])
def root():
    from services.storage import DATA_DIR
    return {
        "status": "running",
        "version": "0.5.0",
        "data_dir": str(DATA_DIR),
        "docs": "http://localhost:8000/docs",
    }
