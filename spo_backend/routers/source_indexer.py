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


class RunBatchRequest(BaseModel):
    thesis_names: list[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

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
