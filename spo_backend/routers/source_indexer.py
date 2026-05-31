"""
Source Indexer Router
---------------------
Thin HTTP layer for the Source Card Indexing pipeline.

Endpoints:
  POST   /source-index/run               — queue single folder
  POST   /source-index/run-batch         — queue batch
  GET    /source-index/status            — poll job statuses
  GET    /source-index/batch-status/{id} — poll batch status
  DELETE /source-index/stop/{name}       — cancel a running job

All thesis_id params are Query params — consistent with every other SPO router.
"""

import uuid
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from services.source_index_service import (
    run_index_sequence,
    run_batch_index_sequence,
    get_index_status,
    get_batch_status,
    cancel_index_job,
    is_index_running,
    generate_batch_id,
    _read_state,
)

router = APIRouter(prefix="/source-index", tags=["Source Card Indexing"])


# ── Request models ─────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    thesis_name: str
    included_files: Optional[list[str]] = None


class RunBatchRequest(BaseModel):
    thesis_names: list[str]
    included_files_map: Optional[dict[str, list[str]]] = None


class SetCardDirRequest(BaseModel):
    thesis_name: str
    card_output_dir: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/set-card-dir", summary="Set the full-card JSON output directory for a thesis folder")
def set_card_dir(req: SetCardDirRequest):
    """
    Validates the directory (or creates it) and saves the path in the drive scan entry.
    All future source index cards for this thesis will be written here.
    """
    from services.storage import read_misc, write_misc
    import os
    from pathlib import Path

    # 1. Validate / create dir
    target_dir = Path(req.card_output_dir).resolve()
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not create or access directory '{target_dir}': {e}"
        )

    # 2. Update scan entry
    scan = read_misc("drive_scan_result", thesis_id="") or {}
    if req.thesis_name not in scan:
        raise HTTPException(
            status_code=404,
            detail=f"Thesis '{req.thesis_name}' not found in scan."
        )

    scan[req.thesis_name]["card_output_dir"] = str(target_dir)
    write_misc("drive_scan_result", scan, thesis_id="")

    return {
        "ok": True,
        "thesis_name": req.thesis_name,
        "card_output_dir": str(target_dir)
    }


@router.get("/full-card/{thesis_name}", summary="Get the complete unsplit NLM JSON for a thesis")
def get_full_card(thesis_name: str):
    """
    Returns the raw parsed JSON returned by NotebookLM (before SPO splits it into source records).
    """
    from services.source_index_service import _safe_name
    from services.storage import read_misc
    
    key = f"source_index_full_{_safe_name(thesis_name)}"
    data = read_misc(key, thesis_id="")
    
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Full card JSON not found for '{thesis_name}'. Has it been indexed yet?"
        )
        
    return data

@router.post("/run", summary="Queue source card indexing for a single thesis folder")
async def run_single(
    req: RunRequest,
    background_tasks: BackgroundTasks,
    thesis_id: str = Query(""),
):
    """
    Kicks off the NLM source card pipeline for one thesis folder as a background
    task. Returns immediately with status 'queued'.

    Returns 409 if a run is already in progress for this folder.
    """
    if await is_index_running(req.thesis_name):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A run is already in progress for '{req.thesis_name}'. "
                "Wait for it to finish or use DELETE /source-index/stop/{thesis_name} to cancel."
            ),
        )

    job_id = f"idx_{uuid.uuid4().hex[:8]}"
    background_tasks.add_task(
        run_index_sequence,
        thesis_name=req.thesis_name,
        thesis_id=thesis_id,
        batch_id=None,
        included_files=req.included_files,
    )

    return {
        "thesis_name": req.thesis_name,
        "status": "queued",
        "job_id": job_id,
    }


@router.post("/run-batch", summary="Queue source card indexing for multiple thesis folders")
async def run_batch(
    req: RunBatchRequest,
    background_tasks: BackgroundTasks,
    thesis_id: str = Query(""),
):
    """
    Splits thesis_names into two async workers. Each worker processes its
    half sequentially — same pattern as the NLM write-section batch.

    The frontend must show a confirmation modal before calling this endpoint.
    """
    if not req.thesis_names:
        raise HTTPException(status_code=400, detail="thesis_names must not be empty.")

    batch_id = generate_batch_id()
    background_tasks.add_task(
        run_batch_index_sequence,
        batch_id=batch_id,
        thesis_names=req.thesis_names,
        thesis_id=thesis_id,
        included_files_map=req.included_files_map,
    )

    return {
        "batch_id": batch_id,
        "jobs": [{"thesis_name": t, "status": "queued"} for t in req.thesis_names],
    }


@router.get("/status", summary="Poll indexing status for one or more thesis folders")
def get_status(
    thesis_names: str = Query(..., description="Comma-separated thesis names"),
    thesis_id: str = Query(""),
):
    """
    Returns current job state for each thesis name.
    Frontend polls this every 3 seconds while jobs are active.
    """
    names = [n.strip() for n in thesis_names.split(",") if n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="thesis_names query param must not be empty.")
    return get_index_status(names)


@router.get(
    "/batch-status/{batch_id}",
    summary="Poll aggregate status for a batch indexing run",
)
def get_batch_status_endpoint(
    batch_id: str,
    thesis_id: str = Query(""),
):
    """Returns the batch progress summary and per-job statuses."""
    status = get_batch_status(batch_id)
    if status["status"] == "unknown":
        raise HTTPException(
            status_code=404, detail=f"Batch '{batch_id}' not found."
        )
    return status


@router.delete(
    "/stop/{thesis_name}",
    summary="Cancel a running source indexing job",
)
async def stop_job(
    thesis_name: str,
    thesis_id: str = Query(""),
):
    """
    Clears the in-memory lock for the given thesis folder and marks the
    state as 'cancelled'. If no job is running, still marks as cancelled
    so the frontend row resets cleanly.
    """
    had_lock = await cancel_index_job(thesis_name)
    return {
        "cancelled": True,
        "thesis_name": thesis_name,
        "was_running": had_lock,
    }
