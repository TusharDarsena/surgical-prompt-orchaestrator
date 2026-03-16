"""
NotebookLM Automation Router
-----------------------------
Automates the Stage 1 writing loop via notebooklm-py:
  compile prompt → create notebook → upload PDFs → send prompt → save draft

Stage 2 (Gemini scholarly elaboration) remains manual — prompt_2 is
returned in the run response for the user to paste into Gemini.

Endpoints:
    GET    /notebooklm/status                                ← credential check
    POST   /notebooklm/run/{chapter_id}/{subtopic_id}        ← trigger run (202 + background)
    GET    /notebooklm/state/{chapter_id}/{subtopic_id}      ← poll run progress
    DELETE /notebooklm/notebook/{chapter_id}/{subtopic_id}   ← delete NLM notebook + clear state
    POST   /notebooklm/summarize/{chapter_id}/{subtopic_id}  ← ask NLM to suggest consistency summary

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLEM 1 — Client lifecycle (FIXED)
  notebooklm-py manages an httpx.AsyncClient internally. The context manager
  `async with await NotebookLMClient.from_storage() as client:` opens and closes
  that httpx session properly. A singleton that never enters the context manager
  leaves the session in an unopened state and every API call will fail.
  FIX: _nlm_client() is an asynccontextmanager that wraps EVERY call in the
  correct `async with await ...` pattern. No singleton.

PROBLEM 2 — add_file with non-PDF files (FIXED)
  notebooklm-py's add_file() auto-detects source type from extension. PDFs are
  fully supported. The risk is if a resolved path somehow points to a non-PDF
  (e.g. a .txt notes file in the same folder). We guard this explicitly:
  - Only files ending in .pdf are uploaded via add_file()
  - Non-PDF files are reported in sources_failed with a clear reason
  - File existence is verified before the API call (avoids a confusing 500)

PROBLEM 3 — Windows asyncio event loop (FIXED)
  FastAPI on Windows uses the ProactorEventLoop by default, which can cause
  issues with asyncio.Lock() and asyncio primitives in background tasks.
  notebooklm-py v0.2.1+ is Windows-tested but the FastAPI app itself needs
  the SelectorEventLoopPolicy set at startup.
  FIX: Add to main.py (see main_nlm_addition.py).
  The router itself is unaffected — the fix goes in main.py.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Setup (one-time):
    pip install "notebooklm-py[browser]"
    playwright install chromium
    notebooklm login          ← opens browser once, writes ~/.notebooklm/storage_state.json

Auth without file (alternative):
    export NOTEBOOKLM_AUTH_JSON='{"cookies":[...]}'
    (copy from ~/.notebooklm/storage_state.json on a machine where login was done)
"""

import logging
import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from services import storage
from services.notebooklm_service import (
    NLMNotInstalledError,
    NLMAuthError,
    _nlm_client,
    is_run_active,
    _build_notebook_title,
    generate_batch_id,
    check_pdf_sizes,
    _run_sequence,
    _run_batch_sequence,
    suggest_summary_service,
    PDF_SIZE_LIMIT_MB,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notebooklm", tags=["NotebookLM Automation"])





# ── Request models ─────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    word_count: Optional[int] = None
    academic_style_notes: Optional[str] = None
    notebook_title: Optional[str] = None


class SummarizeRequest(BaseModel):
    save: bool = False


class BatchRunRequest(BaseModel):
    subtopic_ids: list[str]
    word_count: Optional[int] = None
    academic_style_notes: Optional[str] = None
    notebook_title_prefix: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status", summary="Check if NotebookLM credentials are configured and client is ready")
async def get_nlm_status():
    """
    Opens and immediately closes a client to verify credentials are valid.
    Call on app startup to show whether automation is available.
    Returns ok: true/false with a plain-English message.
    """
    try:
        async with _nlm_client():
            pass
        return {"ok": True, "message": "NotebookLM client is ready."}
    except (NLMNotInstalledError, NLMAuthError) as e:
        return {"ok": False, "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/run/{chapter_id}/{subtopic_id}",
    status_code=202,
    summary="Trigger automated NotebookLM Stage 1 run (returns 202 immediately)"
)
async def run_notebooklm(
    chapter_id: str,
    subtopic_id: str,
    req: RunRequest,
    background_tasks: BackgroundTasks,
    thesis_id: str = Query(""),
):
    """
    Schedules the full Stage 1 automation sequence as a background task:
      1. Compile the prompt (same logic as GET /compile/notebooklm-prompt)
      2. Resolve PDFs to absolute local filesystem paths
      3. Create a new NotebookLM notebook (or reuse existing if re-running)
      4. Upload PDFs — only .pdf files, 2s sleep between each
      5. Send prompt_1, receive response
      6. Save response as section draft (source: "notebooklm_automated")

    Returns 202 immediately.
    Poll GET /notebooklm/state/{chapter_id}/{subtopic_id} for progress.
    Status transitions: idle → running → done | error
    prompt_2 for Stage 2 (Gemini elaboration) is stored in state when done.
    """
    # ── Guard: no duplicate concurrent runs ───────────────────────────────
    if await is_run_active(chapter_id, subtopic_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A run is already in progress for '{subtopic_id}'. "
                "Poll GET /notebooklm/state to check progress."
            )
        )

    # ── Validate before scheduling — fail fast ────────────────────────────
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic '{subtopic_id}' not found in chapter '{chapter_id}'."
        )

    if not subtopic.get("source_ids"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Subtopic '{subtopic_id}' has no source_ids. "
                "Re-import the chapterization JSON with source_ids populated."
            )
        )

    notebook_title = _build_notebook_title(subtopic, override=req.notebook_title)

    background_tasks.add_task(
        _run_sequence,
        chapter_id=chapter_id,
        subtopic_id=subtopic_id,
        chapter=chapter,
        subtopic=subtopic,
        notebook_title=notebook_title,
        word_count=req.word_count,
        academic_style_notes=req.academic_style_notes,
    )

    return {
        "accepted": True,
        "chapter_id": chapter_id,
        "subtopic_id": subtopic_id,
        "message": "Run started. Poll GET /notebooklm/state for progress.",
        "poll_url": f"/notebooklm/state/{chapter_id}/{subtopic_id}",
    }


async def _run_sequence(
    chapter_id: str,
    subtopic_id: str,
    chapter: dict,
    subtopic: dict,
    notebook_title: str,
    word_count: Optional[int],
    academic_style_notes: Optional[str],
    batch_id: Optional[str] = None,
):
    """
    The background sequence. Holds the in-memory run lock for its entire
    duration. State is written to disk at each step so polling stays current.
    """
    run_lock = await _get_run_lock(chapter_id, subtopic_id)

    async with run_lock:
        existing_state = storage.read_nlm_state(chapter_id, subtopic_id) or {}
        state = {
            **existing_state,
            "chapter_id": chapter_id,
            "subtopic_id": subtopic_id,
            "notebook_title": notebook_title,
            "status": "running",
            "last_run_at": datetime.utcnow().isoformat(),
            "run_count": existing_state.get("run_count", 0) + 1,
            "error": None,
            "sources_uploaded": [],
            "sources_failed": [],
            "batch_id": batch_id,
        }
        storage.write_nlm_state(chapter_id, subtopic_id, state)

        try:
            # ── Step 1: compile prompt ─────────────────────────────────────
            # Sync disk reads — run in thread to avoid blocking event loop
            prompts, required_sources = await asyncio.to_thread(
                _compile_prompt_data,
                chapter=chapter,
                subtopic=subtopic,
                chapter_id=chapter_id,
                word_count=word_count,
                academic_style_notes=academic_style_notes,
            )
            prompt_1 = prompts["prompt_1"]
            prompt_2 = prompts["prompt_2"]

            # ── Step 2: resolve absolute paths ────────────────────────────
            # Sync filesystem check — run in thread
            resolved_paths = await asyncio.to_thread(
                _resolve_absolute_paths, required_sources
            )

            # ── Step 3–6: all NotebookLM API calls inside one context ──────
            async with _nlm_client() as client:

                # ── Step 3: create or reuse notebook ──────────────────────
                notebook_id = existing_state.get("notebook_id")
                if not notebook_id:
                    nb = await client.notebooks.create(notebook_title)
                    notebook_id = nb.id
                    logger.info(f"Created notebook '{notebook_id}' for '{subtopic_id}'")
                else:
                    logger.info(f"Reusing existing notebook '{notebook_id}' for '{subtopic_id}'")

                state["notebook_id"] = notebook_id
                storage.write_nlm_state(chapter_id, subtopic_id, state)

                # ── Step 4: upload PDFs ────────────────────────────────────
                uploaded = []
                failed = []

                for path_entry in resolved_paths:
                    file_name = path_entry["file_name"]
                    abs_path = path_entry["abs_path"]

                    # Problem 2 fix: guard against non-PDF files
                    # add_file() auto-detects type by extension, but we only
                    # expect PDFs here. Anything else is flagged and skipped.
                    if not file_name.lower().endswith(".pdf"):
                        failed.append({
                            "file": file_name,
                            "reason": "not a PDF — only .pdf files are uploaded automatically"
                        })
                        logger.warning(f"Skipping non-PDF file '{file_name}'")
                        continue

                    if not abs_path:
                        failed.append({
                            "file": file_name,
                            "reason": (
                                "local path could not be resolved — "
                                "run POST /drive/scan-local first"
                            )
                        })
                        logger.warning(f"No local path resolved for '{file_name}'")
                        continue

                    # Verify file exists before attempting upload
                    # (avoids a confusing error from the notebooklm-py library)
                    if not os.path.isfile(abs_path):
                        failed.append({
                            "file": file_name,
                            "reason": f"file not found at resolved path: {abs_path}"
                        })
                        logger.warning(f"File missing at '{abs_path}'")
                        continue

                    try:
                        await client.sources.add_file(notebook_id, abs_path, wait=True)
                        uploaded.append(file_name)
                        logger.info(f"Uploaded '{file_name}'")
                    except Exception as e:
                        failed.append({"file": file_name, "reason": str(e)})
                        logger.warning(f"Upload failed for '{file_name}': {e}")

                    # Rate-limit buffer between uploads
                    await asyncio.sleep(2)

                state["sources_uploaded"] = uploaded
                state["sources_failed"] = failed
                storage.write_nlm_state(chapter_id, subtopic_id, state)

                if not uploaded:
                    raise RuntimeError(
                        f"No PDFs were uploaded successfully. "
                        f"Failed: {failed}. "
                        "Verify the local scan has run and PDF files exist at resolved paths."
                    )

                # ── Step 5: send prompt_1 ──────────────────────────────────
                logger.info(f"Sending prompt_1 to notebook '{notebook_id}'")
                result = await client.chat.ask(notebook_id, prompt_1)
                draft_text = result.answer

                if not draft_text or not draft_text.strip():
                    raise RuntimeError(
                        "NotebookLM returned an empty response. "
                        "Sources may still be processing — wait 30 seconds and retry."
                    )

                # ── Step 6: save draft ─────────────────────────────────────
                await asyncio.to_thread(
                    storage.write_section_draft,
                    chapter_id,
                    subtopic_id,
                    {
                        "chapter_id": chapter_id,
                        "subtopic_id": subtopic_id,
                        "text": draft_text,
                        "source": "notebooklm_automated",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                )

                # ── Done ───────────────────────────────────────────────────
                state.update({
                    "status": "done",
                    "prompt_2": prompt_2,
                    "draft_preview": (
                        draft_text[:300] + "..."
                        if len(draft_text) > 300
                        else draft_text
                    ),
                    "error": None,
                })
                storage.write_nlm_state(chapter_id, subtopic_id, state)
                logger.info(f"Run complete for subtopic '{subtopic_id}'")

        except Exception as e:
            logger.error(f"Run failed for '{subtopic_id}': {e}", exc_info=True)
            state.update({"status": "error", "error": str(e)})
            storage.write_nlm_state(chapter_id, subtopic_id, state)


# ══════════════════════════════════════════════════════════════════════════════
# STATE
# ══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/state/{chapter_id}/{subtopic_id}",
    summary="Get run state — poll this after triggering /run"
)
async def get_nlm_state(chapter_id: str, subtopic_id: str):
    """
    Returns stored NLM state. The in-memory lock is also checked so the
    status is accurate even if state on disk is stale from a previous run.

    Frontend polling pattern:
        setInterval(() => fetch("/notebooklm/state/..."), 3000)
        stop when status === "done" or "error"

    When status === "done", state includes:
        - prompt_2: the Gemini Stage 2 prompt, ready to paste
        - draft_preview: first 300 chars of the saved draft
        - sources_uploaded / sources_failed: upload audit trail
    """
    active = await is_run_active(chapter_id, subtopic_id)
    state = storage.read_nlm_state(chapter_id, subtopic_id)

    if not state:
        return {
            "chapter_id": chapter_id,
            "subtopic_id": subtopic_id,
            "status": "idle",
            "notebook_id": None,
            "sources_uploaded": [],
            "run_count": 0,
        }

    # If the lock is held but disk state says done/error (new run just
    # started while stale state was on disk), trust the in-memory lock.
    if active and state.get("status") != "running":
        state["status"] = "running"

    return state


# ══════════════════════════════════════════════════════════════════════════════
# DELETE NOTEBOOK
# ══════════════════════════════════════════════════════════════════════════════

@router.delete(
    "/notebook/{chapter_id}/{subtopic_id}",
    summary="Delete the NotebookLM notebook and clear state for a subtopic"
)
async def delete_notebook(chapter_id: str, subtopic_id: str):
    """
    Deletes the notebook via the NotebookLM API and clears stored state.
    The section draft is NOT affected — only the NLM notebook and state.
    Use this when done with a subtopic or to force a completely fresh run.
    """
    if await is_run_active(chapter_id, subtopic_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete notebook while a run is in progress. Wait for it to finish."
        )

    state = storage.read_nlm_state(chapter_id, subtopic_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"No NLM state found for subtopic '{subtopic_id}'. Nothing to delete."
        )

    notebook_id = state.get("notebook_id")
    delete_error = None

    if notebook_id:
        try:
            async with _nlm_client() as client:
                await client.notebooks.delete(notebook_id)
            logger.info(f"Deleted notebook '{notebook_id}' for '{subtopic_id}'")
        except Exception as e:
            # Don't block state cleanup if the notebook was already deleted
            # on the NotebookLM side or credentials are temporarily invalid
            delete_error = str(e)
            logger.warning(f"Notebook API deletion failed for '{notebook_id}': {e}")

    storage.delete_nlm_state(chapter_id, subtopic_id)

    return {
        "deleted": True,
        "subtopic_id": subtopic_id,
        "notebook_id": notebook_id,
        "api_delete_error": delete_error,
        "message": (
            "Notebook deleted and state cleared. Draft was not affected."
            if not delete_error
            else f"State cleared. Notebook API deletion failed: {delete_error}"
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BATCH RUN
# ══════════════════════════════════════════════════════════════════════════════




@router.post(
    "/run-batch/{chapter_id}",
    status_code=202,
    summary="Trigger parallel batch run for multiple subtopics (2-worker split)",
)
async def run_batch(
    chapter_id: str,
    req: BatchRunRequest,
    background_tasks: BackgroundTasks,
    thesis_id: str = Query(""),
):
    """
    Splits subtopic_ids into two halves and runs them in parallel — each half
    is processed sequentially within its worker so order is preserved.

    Example: 8 subtopics → Worker A handles [0,1,2,3], Worker B handles [4,5,6,7].
    Both workers run concurrently; within each worker subtopics run one after another.

    previous_summary context is NOT used in batch runs — each subtopic is
    compiled independently.

    PDF guard: any resolved PDF > 5 MB blocks the entire batch before it starts.
    Returns 202 immediately. Poll GET /notebooklm/batch-state/{batch_id} for progress.
    Poll GET /notebooklm/state/{chapter_id}/{subtopic_id} for per-subtopic detail.
    """
    if not req.subtopic_ids:
        raise HTTPException(status_code=422, detail="subtopic_ids cannot be empty.")

    # ── Load and validate chapter ─────────────────────────────────────────────
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics_map = {s["subtopic_id"]: s for s in chapter.get("subtopics", [])}

    # ── Validate every subtopic_id and check for active runs ─────────────────
    validated: list[dict] = []
    for sid in req.subtopic_ids:
        subtopic = subtopics_map.get(sid)
        if not subtopic:
            raise HTTPException(
                status_code=404,
                detail=f"Subtopic '{sid}' not found in chapter '{chapter_id}'.",
            )
        if not subtopic.get("source_ids"):
            raise HTTPException(
                status_code=422,
                detail=f"Subtopic '{sid}' has no source_ids. Re-import chapterization JSON.",
            )
        if await is_run_active(chapter_id, sid):
            raise HTTPException(
                status_code=409,
                detail=f"Subtopic '{sid}' already has a run in progress.",
            )
        validated.append(subtopic)

    # ── PDF size pre-check (resolve paths for all subtopics upfront) ──────────
    oversized = await check_pdf_sizes(validated)
    if oversized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Batch blocked. {len(oversized)} PDF(s) exceed the {PDF_SIZE_LIMIT_MB} MB limit. "
                    "Split large PDFs into smaller files before running."
                ),
                "oversized_files": oversized,
            },
        )

    # ── Build batch_id and initial batch state ────────────────────────────────
    batch_id = generate_batch_id(chapter_id)

    storage.write_batch_state(batch_id, {
        "batch_id": batch_id,
        "chapter_id": chapter_id,
        "subtopic_ids": req.subtopic_ids,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "worker_a": req.subtopic_ids[: math.ceil(len(req.subtopic_ids) / 2)],
        "worker_b": req.subtopic_ids[math.ceil(len(req.subtopic_ids) / 2) :],
    })

    # ── Schedule background batch ─────────────────────────────────────────────
    background_tasks.add_task(
        _run_batch_sequence,
        batch_id=batch_id,
        chapter_id=chapter_id,
        subtopics_map=subtopics_map,
        subtopic_ids=req.subtopic_ids,
        word_count=req.word_count,
        academic_style_notes=req.academic_style_notes,
        notebook_title_prefix=req.notebook_title_prefix,
    )

    return {
        "accepted": True,
        "batch_id": batch_id,
        "chapter_id": chapter_id,
        "subtopic_ids": req.subtopic_ids,
        "worker_a": req.subtopic_ids[: math.ceil(len(req.subtopic_ids) / 2)],
        "worker_b": req.subtopic_ids[math.ceil(len(req.subtopic_ids) / 2) :],
        "message": "Batch started. Poll GET /notebooklm/batch-state/{batch_id} for progress.",
        "poll_url": f"/notebooklm/batch-state/{batch_id}",
    }


async def _run_batch_sequence(
    batch_id: str,
    chapter_id: str,
    subtopics_map: dict,
    subtopic_ids: list[str],
    word_count: Optional[int],
    academic_style_notes: Optional[str],
    notebook_title_prefix: Optional[str],
):
    """
    Splits subtopic_ids into two halves and runs them with asyncio.gather.
    Each worker processes its half sequentially.
    Writes final batch state when both workers complete.
    """
    mid = math.ceil(len(subtopic_ids) / 2)
    worker_a_ids = subtopic_ids[:mid]
    worker_b_ids = subtopic_ids[mid:]

    async def _worker(ids: list[str]):
        for sid in ids:
            subtopic = subtopics_map[sid]
            title_prefix = notebook_title_prefix or "SPO"
            notebook_title = (
                f"{title_prefix} — {subtopic.get('number', sid)} {subtopic.get('title', '')}"
            )[:100]
            await _run_sequence(
                chapter_id=chapter_id,
                subtopic_id=sid,
                chapter={"subtopics": list(subtopics_map.values())},
                subtopic=subtopic,
                notebook_title=notebook_title,
                word_count=word_count,
                academic_style_notes=academic_style_notes,
                batch_id=batch_id,
            )

    try:
        await asyncio.gather(_worker(worker_a_ids), _worker(worker_b_ids))
        final_status = "done"
    except Exception as e:
        logger.error(f"Batch '{batch_id}' encountered an unexpected error: {e}", exc_info=True)
        final_status = "error"

    # ── Update batch state to reflect completion ──────────────────────────────
    batch_state = storage.read_batch_state(batch_id) or {}
    batch_state.update({
        "status": final_status,
        "completed_at": datetime.utcnow().isoformat(),
    })
    storage.write_batch_state(batch_id, batch_state)


@router.get(
    "/batch-state/{batch_id}",
    summary="Aggregate progress for a batch run",
)
async def get_batch_state(batch_id: str):
    """
    Reads the batch manifest, then reads each subtopic's individual nlm_state
    and aggregates into a single progress view.

    Returns:
        status        — running | done | error (derived from subtopic states)
        progress      — { total, done, running, error, pending }
        subtopics     — per-subtopic status snapshot (no draft text, just status)
        completed_at  — set when all subtopics have reached done or error
    """
    batch = storage.read_batch_state(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found.")

    chapter_id = batch["chapter_id"]
    subtopic_ids = batch["subtopic_ids"]

    counts = {"done": 0, "running": 0, "error": 0, "pending": 0}
    subtopic_snapshots = []

    for sid in subtopic_ids:
        state = storage.read_nlm_state(chapter_id, sid)
        # Also check in-memory lock — a task might be running before first disk write
        active = await is_run_active(chapter_id, sid)

        if state is None:
            status = "running" if active else "pending"
        else:
            status = state.get("status", "pending")
            if active and status != "running":
                status = "running"

        counts[status] = counts.get(status, 0) + 1
        subtopic_snapshots.append({
            "subtopic_id": sid,
            "status": status,
            "error": state.get("error") if state else None,
            "sources_uploaded": state.get("sources_uploaded", []) if state else [],
            "sources_failed": state.get("sources_failed", []) if state else [],
            "poll_url": f"/notebooklm/state/{chapter_id}/{sid}",
        })

    total = len(subtopic_ids)
    all_terminal = (counts["done"] + counts["error"]) == total
    derived_status = (
        "done" if counts["error"] == 0 and all_terminal
        else "error" if all_terminal
        else "running"
    )

    return {
        "batch_id": batch_id,
        "chapter_id": chapter_id,
        "status": derived_status,
        "progress": {
            "total": total,
            "done": counts["done"],
            "running": counts["running"],
            "error": counts["error"],
            "pending": counts["pending"],
            "percent": round((counts["done"] / total) * 100) if total else 0,
        },
        "worker_a": batch.get("worker_a", []),
        "worker_b": batch.get("worker_b", []),
        "started_at": batch.get("started_at"),
        "completed_at": batch.get("completed_at"),
        "subtopics": subtopic_snapshots,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARIZE
# ══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/summarize/{chapter_id}/{subtopic_id}",
    summary="Ask the NotebookLM notebook to suggest a consistency summary"
)
async def suggest_summary(
    chapter_id: str,
    subtopic_id: str,
    req: SummarizeRequest,
    thesis_id: str = Query(""),
):
    """
    Sends a structured prompt to the existing notebook asking it to produce
    a consistency summary: what was argued, key terms, bridge to next section.
    Does NOT auto-save by default — review the suggestion first.
    Pass save: true in the body to auto-save it to the consistency chain.
    Requires a completed run (notebook_id must exist in state).
    """
    state = storage.read_nlm_state(chapter_id, subtopic_id)
    if not state or not state.get("notebook_id"):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No notebook found for subtopic '{subtopic_id}'. "
                "Complete a run first via POST /notebooklm/run."
            )
        )

    if state.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Run still in progress. Wait for it to finish."
        )

    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(status_code=404, detail=f"Subtopic '{subtopic_id}' not found.")

    try:
        return await suggest_summary_service(
            chapter_id=chapter_id,
            subtopic_id=subtopic_id,
            subtopic=subtopic,
            notebook_id=state["notebook_id"],
            save=req.save,
        )
    except (NLMNotInstalledError, NLMAuthError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

