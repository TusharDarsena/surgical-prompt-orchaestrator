"""
SPO Backend — Surgical Prompt Orchestrator v0.4.0
Run from the spo_backend directory:
    uvicorn main:app --reload --port 8000
"""

# ── Windows asyncio fix — must be FIRST, before any asyncio import ────────────
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())  # walks up from spo_backend/ to find .env at project root

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import thesis, sources, consistency, notes, compiler, importer, drive, sections
from routers import notebooklm

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


@app.get("/", tags=["Health"])
def root():
    from services.storage import DATA_DIR
    return {
        "status": "running",
        "version": "0.5.0",
        "data_dir": str(DATA_DIR),
        "docs": "http://localhost:8000/docs",
    }