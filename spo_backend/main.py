"""
SPO Backend — Surgical Prompt Orchestrator v0.4.0
Run from the spo_backend directory:
    uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import thesis, sources, consistency, notes, compiler, importer, drive

app = FastAPI(
    title="SPO — Surgical Prompt Orchestrator",
    description=(
        "Prompt stitching engine for academic writing. "
        "v0.4: Chapterization JSON → NotebookLM prompt directly. "
        "Bulk chapterization import. Source guidance per subtopic."
    ),
    version="0.4.0",
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


@app.get("/", tags=["Health"])
def root():
    from services.storage import DATA_DIR
    return {
        "status": "running",
        "version": "0.4.0",
        "data_dir": str(DATA_DIR),
        "docs": "http://localhost:8000/docs",
    }