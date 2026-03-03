"""
SPO Backend — Surgical Prompt Orchestrator
==========================================
FastAPI backend for the SPO system.

Core principle: This app is a PROMPT STITCHING ENGINE.
It does NOT call any AI APIs. It manages your thesis structure, source library,
and consistency chain so you can generate perfect prompts to paste into
Claude (for Task.md) and NotebookLM (for writing).

Run with:
    uvicorn main:app --reload --port 8000

Docs at: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import thesis, sources, consistency, notes, compiler

app = FastAPI(
    title="SPO — Surgical Prompt Orchestrator",
    description=(
        "Backend for managing thesis context, source library (with index cards), "
        "and consistency chain. Generates structured data for Architect Mega-Prompts "
        "and NotebookLM handoffs."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Streamlit will run locally
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(thesis.router)
app.include_router(sources.router)
app.include_router(consistency.router)
app.include_router(notes.router)
app.include_router(compiler.router)


@app.get("/", tags=["Health"])
def root():
    return {
        "status": "running",
        "system": "SPO — Surgical Prompt Orchestrator",
        "docs": "/docs",
        "principle": "Prompt stitching engine. No AI calls. No database. Just structured JSON on disk.",
    }


@app.get("/health", tags=["Health"])
def health():
    from services.storage import DATA_DIR
    return {
        "status": "ok",
        "data_dir": str(DATA_DIR),
        "data_dir_exists": DATA_DIR.exists(),
    }