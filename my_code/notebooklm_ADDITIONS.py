# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADDITIONS TO: spo_backend/routers/notebooklm.py
#
# 1. ADD this import at the top of the file (with the existing service imports):
#      from services.notebooklm_service import (
#          ...existing imports...,
#          is_ic_run_active,
#          _generate_index_card_sequence,
#          _generate_index_card_batch_sequence,
#      )
#
#    SIMPLEST APPROACH — replace the existing import block:
#
# OLD:
# from services.notebooklm_service import (
#     NLMNotInstalledError,
#     NLMAuthError,
#     _nlm_client,
#     is_run_active,
#     _build_notebook_title,
#     generate_batch_id,
#     check_pdf_sizes,
#     _run_sequence,
#     _run_batch_sequence,
#     suggest_summary_service,
#     PDF_SIZE_LIMIT_MB,
# )
#
# NEW:
# from services.notebooklm_service import (
#     NLMNotInstalledError,
#     NLMAuthError,
#     _nlm_client,
#     is_run_active,
#     _build_notebook_title,
#     generate_batch_id,
#     check_pdf_sizes,
#     _run_sequence,
#     _run_batch_sequence,
#     suggest_summary_service,
#     PDF_SIZE_LIMIT_MB,
#     is_ic_run_active,
#     _generate_index_card_sequence,
#     _generate_index_card_batch_sequence,
# )
#
# 2. ADD this model alongside the existing request models:
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class IndexCardBatchRequest(BaseModel):
    scan_keys: list[str]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. ADD these three endpoints at the end of notebooklm.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ══════════════════════════════════════════════════════════════════════════════
# INDEX CARD GENERATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/generate-index-cards",
    status_code=202,
    summary="Auto-generate source index cards for one or more thesis folders via NotebookLM",
)
async def generate_index_cards(
    req: IndexCardBatchRequest,
    background_tasks: BackgroundTasks,
):
    """
    For each scan_key (thesis folder name):
      - Filters PDFs to chapters + abstract/conclusion/title only
      - Creates a NLM notebook, uploads the filtered PDFs
      - Sends prompts/generate_source_json.txt
      - Parses JSON response, saves raw JSON to disk, calls do_auto_import()
      - Updates drive_scan_result import_status

    Single scan_key → direct background task, no batch overhead.
    Multiple scan_keys → two-worker parallel batch (same pattern as /run-batch).

    Returns 202 immediately. Poll:
      Single: GET /notebooklm/index-card-state?thesis_name=...
      Batch:  GET /notebooklm/index-card-batch-state/{batch_id}
    """
    if not req.scan_keys:
        raise HTTPException(status_code=422, detail="scan_keys cannot be empty.")

    scan = storage.read_misc("drive_scan_result") or {}
    for key in req.scan_keys:
        if key not in scan:
            raise HTTPException(
                status_code=404,
                detail=f"Thesis '{key}' not found in drive scan. Run POST /drive/scan-local first.",
            )
        if await is_ic_run_active(key):
            raise HTTPException(
                status_code=409,
                detail=f"Index card generation already running for '{key}'.",
            )

    if len(req.scan_keys) == 1:
        thesis_name = req.scan_keys[0]
        background_tasks.add_task(_generate_index_card_sequence, thesis_name)
        return {
            "accepted": True,
            "thesis_name": thesis_name,
            "message": "Index card generation started.",
            "poll_url": f"/notebooklm/index-card-state?thesis_name={thesis_name}",
        }

    # Batch path
    batch_id = f"ic_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    mid = math.ceil(len(req.scan_keys) / 2)

    storage.write_misc(f"ic_batch_{batch_id}", {
        "batch_id": batch_id,
        "scan_keys": req.scan_keys,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "worker_a": req.scan_keys[:mid],
        "worker_b": req.scan_keys[mid:],
    })

    background_tasks.add_task(
        _generate_index_card_batch_sequence,
        batch_id=batch_id,
        thesis_names=req.scan_keys,
    )

    return {
        "accepted": True,
        "batch_id": batch_id,
        "scan_keys": req.scan_keys,
        "worker_a": req.scan_keys[:mid],
        "worker_b": req.scan_keys[mid:],
        "message": "Batch index card generation started.",
        "poll_url": f"/notebooklm/index-card-batch-state/{batch_id}",
    }


@router.get(
    "/index-card-state",
    summary="Get index card generation state for a thesis folder (poll after /generate-index-cards)",
)
async def get_ic_state(thesis_name: str = Query(..., description="Thesis folder name (scan key)")):
    """
    Returns IC run state for a single thesis. Uses query param (not path param)
    to safely handle thesis names with spaces and special characters.

    status values: idle | running | done | error
    """
    active = await is_ic_run_active(thesis_name)
    state = storage.read_misc(f"ic_run_{thesis_name}")

    if not state:
        return {"thesis_name": thesis_name, "status": "idle"}

    # If lock is held but stale state on disk from a previous run, trust the lock
    if active and state.get("status") != "running":
        state["status"] = "running"

    return state


@router.get(
    "/index-card-batch-state/{batch_id}",
    summary="Aggregate progress for a batch index card generation run",
)
async def get_ic_batch_state(batch_id: str):
    """
    Reads the batch manifest then aggregates per-thesis IC states.
    Mirrors get_batch_state() for write-section batches exactly.
    """
    batch = storage.read_misc(f"ic_batch_{batch_id}")
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    scan_keys = batch.get("scan_keys", [])
    counts = {"done": 0, "running": 0, "error": 0, "pending": 0}
    snapshots = []

    for key in scan_keys:
        active = await is_ic_run_active(key)
        state = storage.read_misc(f"ic_run_{key}")

        if state is None:
            status = "running" if active else "pending"
        else:
            status = state.get("status", "pending")
            if active and status != "running":
                status = "running"

        counts[status] = counts.get(status, 0) + 1
        snapshots.append({
            "thesis_name": key,
            "status": status,
            "sources_created": state.get("sources_created", 0) if state else 0,
            "files_uploaded": state.get("files_uploaded", []) if state else [],
            "error": state.get("error") if state else None,
            "poll_url": f"/notebooklm/index-card-state?thesis_name={key}",
        })

    total = len(scan_keys)
    all_terminal = (counts["done"] + counts["error"]) == total
    derived_status = (
        "done"    if counts["error"] == 0 and all_terminal else
        "error"   if all_terminal else
        "running"
    )

    return {
        "batch_id": batch_id,
        "status": derived_status,
        "progress": {
            "total":   total,
            "done":    counts["done"],
            "running": counts["running"],
            "error":   counts["error"],
            "pending": counts["pending"],
            "percent": round((counts["done"] / total) * 100) if total else 0,
        },
        "worker_a":    batch.get("worker_a", []),
        "worker_b":    batch.get("worker_b", []),
        "started_at":  batch.get("started_at"),
        "completed_at": batch.get("completed_at"),
        "theses":      snapshots,
    }
