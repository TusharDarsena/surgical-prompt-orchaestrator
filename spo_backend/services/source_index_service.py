"""
Source Index Service
--------------------
NLM pipeline for automated source card generation per thesis folder.

Pipeline:
  1. Load generate_source_json.txt prompt
  2. Resolve Drive file IDs + local paths via _resolve_absolute_paths
  3. Size guard: reject files > 10 MB
  4. Create / reuse NLM notebook per thesis folder
  5. Upload PDFs via add_drive (Drive) or add_file (local)
  6. Partial-upload guard: halt if any file failed
  7. 10-second indexing buffer
  8. Ask NLM with prompt — wrapped in wait_for(timeout=300s)
  9. Clean NLM JSON (strip fences + trailing commas)
  10. do_auto_import + quality check
  11. Write import_status back to drive_scan_result.json
  12. Update per-thesis state file

Exception contract:
  NLMNotInstalledError / NLMAuthError  → caught, stored as error state
  All others                           → caught, stored as error state
"""

import asyncio
import json
import logging
import math
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from services import storage
from services.source_importer import do_auto_import
from services.notebooklm_service import (
    _nlm_client,
    _ask_with_retry,
    _resolve_absolute_paths,
    NLMNotInstalledError,
    NLMAuthError,
    _upload_semaphore,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SCAN_KEY = "drive_scan_result"
PDF_SIZE_LIMIT_MB = 10.0
_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "generate_source_json.txt"

# ── In-memory mutex registry ───────────────────────────────────────────────────
# Keyed by thesis_name. Blocks double-click spawning two upload loops.
# Intentionally NOT persisted — vanishes on restart (no zombie locks after crash).

_index_locks: dict[str, asyncio.Lock] = {}
_locks_registry_lock = asyncio.Lock()

# ── Active task registry (Fix 1) ───────────────────────────────────────────────
# Stores the asyncio.Task reference so cancel_index_job can actually stop execution.
# lock.pop() alone only orphans the lock — the task keeps running.

_active_tasks: dict[str, asyncio.Task] = {}


async def _get_index_lock(thesis_name: str) -> asyncio.Lock:
    async with _locks_registry_lock:
        if thesis_name not in _index_locks:
            _index_locks[thesis_name] = asyncio.Lock()
        return _index_locks[thesis_name]


async def is_index_running(thesis_name: str) -> bool:
    """Public check for the router — is this thesis currently being indexed?"""
    lock = await _get_index_lock(thesis_name)
    return lock.locked()


# ── safe_name ─────────────────────────────────────────────────────────────────

def _safe_name(thesis_name: str) -> str:
    """Sanitize thesis name for use as a misc storage key / filename."""
    return (
        thesis_name
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(",", "_")
        .replace(" ", "_")
    )


# ── State helpers ──────────────────────────────────────────────────────────────

def _read_state(thesis_name: str) -> dict:
    key = f"source_index_{_safe_name(thesis_name)}"
    return storage.read_misc(key, thesis_id="") or {}


def _write_state(thesis_name: str, state: dict) -> None:
    key = f"source_index_{_safe_name(thesis_name)}"
    storage.write_misc(key, state, thesis_id="")


def _read_scan() -> dict:
    return storage.read_misc(SCAN_KEY, thesis_id="") or {}


def _write_scan(data: dict) -> None:
    storage.write_misc(SCAN_KEY, data, thesis_id="")


# ── JSON cleaning (mirrors suggest_summary_service) ────────────────────────────

def _clean_nlm_json(raw_text: str) -> dict:
    """
    Strip markdown fences and trailing commas from NLM response, then parse.
    Raises ValueError / json.JSONDecodeError on failure.
    """
    clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
    clean = re.sub(r',\s*([}\]])', r'\1', clean)
    return json.loads(clean)


# ── Prompt loader ──────────────────────────────────────────────────────────────

def _load_prompt() -> str:
    if not _PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {_PROMPT_PATH}. "
            "Expected at <project_root>/prompts/generate_source_json.txt"
        )
    return _PROMPT_PATH.read_text(encoding="utf-8")


# ── Build required_sources list for _resolve_absolute_paths ────────────────────

def _build_required_sources(thesis_name: str, scan_entry: dict) -> list[dict]:
    """
    Converts the flat files list + drive_links in the scan entry into the
    format expected by _resolve_absolute_paths:
      [{ source_id: thesis_name, file_name: "...", drive_link: "..." | None }]
    """
    files = scan_entry.get("files", [])
    drive_links = scan_entry.get("drive_links", {})
    return [
        {
            "source_id": thesis_name,
            "file_name": fname,
            "drive_link": drive_links.get(fname),
        }
        for fname in files
        if fname.lower().endswith(".pdf")
    ]


# ── Batch ID helper ────────────────────────────────────────────────────────────

def generate_batch_id() -> str:
    return f"source_batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"


# ── Core single-folder pipeline ────────────────────────────────────────────────

async def run_index_sequence(
    thesis_name: str,
    thesis_id: str = "",
    batch_id: Optional[str] = None,
    skip_if_done: bool = False,
    included_files: Optional[list[str]] = None,
) -> None:
    """
    Full NLM source-card pipeline for one thesis folder.
    Writes state to misc/source_index_{safe_name}.json at each step.
    Must be called as a background task — never awaited directly by the router.

    skip_if_done=True: used by batch runner to avoid re-running a folder that
    a concurrent single run already indexed while the batch was waiting on the lock.
    """
    lock = await _get_index_lock(thesis_name)

    try:
        # Fix 1: register task reference so cancel_index_job can actually stop it
        _active_tasks[thesis_name] = asyncio.current_task()

        async with lock:
            # Fix 2 (batch guard): re-check state after acquiring lock.
            # If a single run finished this folder while we were waiting, skip.
            if skip_if_done:
                current_status = _read_state(thesis_name).get("status", "idle")
                if current_status in ("done", "warn"):
                    logger.info(
                        f"Skipping '{thesis_name}' — already indexed "
                        f"(status={current_status}) by a concurrent run."
                    )
                    return

            state = _read_state(thesis_name)
            state.update({
                "thesis_name": thesis_name,
                "status": "running",
                "batch_id": batch_id,
                "last_run_at": datetime.utcnow().isoformat(),
                "run_count": state.get("run_count", 0) + 1,
                "sources_uploaded": [],
                "sources_failed": [],
                "missing_sources": [],
                "error": None,
                "warn_message": None,
                "group_id": None,
                "sources_created": 0,
            })
            _write_state(thesis_name, state)

            try:
                # ── Step 1: Load prompt ────────────────────────────────────────
                prompt_text = await asyncio.to_thread(_load_prompt)

                # ── Step 2: Read scan entry ────────────────────────────────────
                scan = await asyncio.to_thread(_read_scan)
                scan_entry = scan.get(thesis_name)
                if not scan_entry:
                    raise RuntimeError(
                        f"Thesis '{thesis_name}' not found in drive_scan_result. "
                        "Run POST /drive/scan-local first."
                    )

                # ── Step 3: Build required_sources + resolve paths ─────────────
                required_sources = _build_required_sources(thesis_name, scan_entry)
                if not required_sources:
                    raise RuntimeError(
                        f"No PDF files found for '{thesis_name}' in scan entry."
                    )

                # ── Step 3b: Filter to user-selected files only ────────────────
                if included_files is not None:
                    included_set = set(included_files)
                    required_sources = [r for r in required_sources if r["file_name"] in included_set]
                    if not required_sources:
                        raise RuntimeError(
                            "No files selected for upload. Select at least one PDF before running."
                        )

                resolved = await asyncio.to_thread(_resolve_absolute_paths, required_sources)

                # ── Step 4: File size guard ────────────────────────────────────
                oversized = [
                    r["file_name"]
                    for r in resolved
                    if r.get("file_size_mb") is not None and r["file_size_mb"] > PDF_SIZE_LIMIT_MB
                ]
                if oversized:
                    raise RuntimeError(
                        f"file_too_large: {len(oversized)} PDF(s) exceed {PDF_SIZE_LIMIT_MB} MB: "
                        f"{oversized}. Remove or split them and re-run."
                    )

                # ── Step 5: Open NLM client ────────────────────────────────────
                async with _nlm_client() as client:

                    # ── Step 6: Create / reuse notebook ───────────────────────
                    # Fallback to state if scan_entry lost it due to old bug
                    notebook_id = scan_entry.get("index_notebook_id") or state.get("index_notebook_id")
                    if notebook_id:
                        try:
                            await client.notebooks.get(notebook_id)
                            logger.info(f"Reusing notebook '{notebook_id}' for '{thesis_name}'")
                        except Exception as e:
                            logger.warning(
                                f"Notebook '{notebook_id}' inaccessible, creating new. Error: {e}"
                            )
                            notebook_id = None

                    if not notebook_id:
                        nb = await client.notebooks.create(
                            f"SPO Source Index — {thesis_name}"[:100]
                        )
                        notebook_id = nb.id
                        logger.info(f"Created notebook '{notebook_id}' for '{thesis_name}'")

                    state["index_notebook_id"] = notebook_id
                    _write_state(thesis_name, state)

                    # Bug fix: persist notebook ID to scan entry immediately after create/reuse
                    # so it survives import failures and is reused on the next run.
                    _scan_for_nb = await asyncio.to_thread(_read_scan)
                    if thesis_name in _scan_for_nb:
                        _scan_for_nb[thesis_name]["index_notebook_id"] = notebook_id
                        await asyncio.to_thread(_write_scan, _scan_for_nb)

                    # ── Step 7: Capacity check ─────────────────────────────────
                    try:
                        existing_sources = await client.sources.list(notebook_id)
                    except Exception as e:
                        logger.warning(f"Could not list existing sources: {e}")
                        existing_sources = []

                    existing_filenames = {
                        os.path.splitext(s.title)[0].lower()
                        for s in existing_sources
                    }

                    # Determine which files can actually be uploaded
                    resolvable = [
                        r for r in resolved
                        if r.get("drive_file_id") or (r.get("abs_path") and os.path.isfile(r["abs_path"]))
                    ]
                    new_files = [
                        r for r in resolvable
                        if os.path.splitext(r["file_name"])[0].lower() not in existing_filenames
                    ]

                    if len(existing_sources) + len(new_files) > 50:
                        raise RuntimeError(
                            f"Notebook capacity exceeded: {len(existing_sources)} existing + "
                            f"{len(new_files)} new = {len(existing_sources) + len(new_files)} > 50 limit."
                        )

                    # ── Step 8: Upload loop ────────────────────────────────────
                    uploaded: list[str] = []
                    failed: list[dict] = []

                    for r in resolvable:
                        fname = r["file_name"]
                        name_no_ext = os.path.splitext(fname)[0].lower()

                        # Skip already-present files
                        if name_no_ext in existing_filenames:
                            logger.info(f"Skipping '{fname}' (already in notebook)")
                            uploaded.append(fname)
                            continue

                        try:
                            async with _upload_semaphore:
                                if r.get("drive_file_id"):
                                    await asyncio.wait_for(
                                        client.sources.add_drive(
                                            notebook_id,
                                            file_id=r["drive_file_id"],
                                            mime_type="application/pdf",
                                            title=fname,
                                            wait=True,
                                        ),
                                        timeout=180.0,
                                    )
                                else:
                                    await asyncio.wait_for(
                                        client.sources.add_file(
                                            notebook_id, r["abs_path"], wait=True
                                        ),
                                        timeout=180.0,
                                    )
                            uploaded.append(fname)
                            logger.info(f"Uploaded '{fname}'")
                        except asyncio.TimeoutError:
                            failed.append({"file": fname, "reason": "upload timed out after 3 minutes"})
                            logger.warning(f"Upload timeout: '{fname}'")
                        except Exception as e:
                            failed.append({"file": fname, "reason": str(e)})
                            logger.warning(f"Upload failed '{fname}': {e}")

                    state["sources_uploaded"] = uploaded
                    state["sources_failed"] = failed
                    _write_state(thesis_name, state)

                    # ── Step 9: Partial-upload guard ───────────────────────────
                    if not resolvable:
                        raise RuntimeError(
                            f"No uploadable files for '{thesis_name}'. "
                            "Check that Drive links are registered or local paths are valid."
                        )

                    if len(uploaded) < len(resolvable):
                        missing = [
                            {"file": r["file_name"], "drive_link": r.get("drive_link")}
                            for r in resolvable
                            if r["file_name"] not in uploaded
                        ]
                        state.update({
                            "status": "waiting_for_manual_upload",
                            "missing_sources": missing,
                        })
                        _write_state(thesis_name, state)
                        logger.warning(
                            f"Partial upload for '{thesis_name}'. "
                            f"Missing: {missing}. Halting pipeline."
                        )
                        return

                    # ── Step 10: Post-upload indexing buffer ───────────────────
                    new_files_uploaded = [
                        f for f in uploaded
                        if os.path.splitext(f)[0].lower() not in existing_filenames
                    ]
                    if new_files_uploaded:
                        logger.info(f"Waiting 10s for NLM to index {len(new_files_uploaded)} new sources…")
                        await asyncio.sleep(10)

                    # ── Step 11: Send prompt ───────────────────────────────────
                    logger.info(f"Sending source card prompt to notebook '{notebook_id}'")
                    try:
                        raw_answer = await asyncio.wait_for(
                            _ask_with_retry(client, notebook_id, prompt_text),
                            timeout=300.0,
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            "NLM prompt timed out after 5 minutes. "
                            "The notebook may be processing a large folder — try re-running."
                        )

                    # ── Step 12: Clean + parse JSON ────────────────────────────
                    try:
                        parsed = _clean_nlm_json(raw_answer)
                    except (json.JSONDecodeError, ValueError) as e:
                        raise RuntimeError(
                            f"NLM returned invalid JSON: {e}. "
                            f"Raw response (first 500 chars): {raw_answer[:500]}"
                        )

                    # ── Step 12b: Save full JSON to disk and misc storage ──────
                    # Written BEFORE do_auto_import so data survives a validation
                    # crash. If import fails, user can manually inspect the file.
                    #
                    # Output path priority:
                    #   1. card_output_dir (user-chosen, per-thesis, set via UI)
                    #   2. folder_path/index_cards (legacy local fallback)
                    # Always also writes to spo_data/misc so Drive-mode runs
                    # (no local folder_path) are covered too.
                    full_card_key = f"source_index_full_{_safe_name(thesis_name)}"
                    json_backup_path: Optional[str] = None

                    card_output_dir = scan_entry.get("card_output_dir")
                    folder_path = scan_entry.get("folder_path", "")

                    if card_output_dir:
                        disk_dir = card_output_dir
                    elif folder_path:
                        disk_dir = os.path.join(folder_path, "index_cards")
                    else:
                        disk_dir = None

                    if disk_dir:
                        try:
                            os.makedirs(disk_dir, exist_ok=True)
                            json_backup_path = os.path.join(
                                disk_dir, f"{_safe_name(thesis_name)}.json"
                            )
                            with open(json_backup_path, "w", encoding="utf-8") as fh:
                                json.dump(parsed, fh, indent=2, ensure_ascii=False)
                            logger.info(f"Raw JSON saved to: {json_backup_path}")
                        except Exception as backup_err:
                            logger.warning(
                                f"Could not save JSON to disk for '{thesis_name}': {backup_err}"
                            )
                            json_backup_path = None

                    # Always write misc copy (Drive-mode safe, queryable via API)
                    try:
                        storage.write_misc(full_card_key, parsed, thesis_id="")
                        logger.info(f"Full card JSON written to misc key '{full_card_key}'")
                    except Exception as misc_err:
                        logger.warning(f"Could not write misc copy for '{thesis_name}': {misc_err}")


                    # ── Step 13: Auto-import ───────────────────────────────────
                    import_result, import_error = do_auto_import(
                        parsed, thesis_id=thesis_id, scan_key=thesis_name
                    )
                    if import_error:
                        raise RuntimeError(f"Import failed: {import_error}")

                    sources_created = import_result["sources_created"]
                    group_id = import_result["group_id"]

                    # ── Step 14: Quality check ─────────────────────────────────
                    DEFAULT_CLAIMS = {"No specific claims extracted."}
                    DEFAULT_THEMES = {"uncategorized"}
                    all_chapters = parsed.get("chapters", [])
                    
                    def _is_empty_or_default(val, defaults):
                        if not val:
                            return True
                        if isinstance(val, str):
                            return val in defaults
                        try:
                            return set(val) <= defaults
                        except Exception:
                            return True

                    problematic_chapters = []
                    for i, ch in enumerate(all_chapters):
                        if _is_empty_or_default(ch.get("key_claims"), DEFAULT_CLAIMS) or \
                           _is_empty_or_default(ch.get("themes"), DEFAULT_THEMES):
                            
                            # Try to get a readable name, fallback to index
                            name = ch.get("label") or ch.get("title") or ch.get("file_name") or f"Chapter {i+1}"
                            problematic_chapters.append(name)

                    if sources_created == 0 or problematic_chapters:
                        final_status = "warn"
                        if sources_created == 0:
                            warn_message = "Indexed but no sources were created."
                        else:
                            names_str = ", ".join(problematic_chapters)
                            warn_message = (
                                f"Indexed but may be incomplete — "
                                f"default/empty key_claims or themes in: {names_str}"
                            )
                        logger.warning(f"Quality check warning for '{thesis_name}': {warn_message}")
                    else:
                        final_status = "done"
                        warn_message = None

                    # ── Step 15: Update scan entry ─────────────────────────────
                    scan = await asyncio.to_thread(_read_scan)
                    if thesis_name in scan:
                        scan[thesis_name]["import_status"] = {
                            "imported": True,
                            "imported_at": datetime.utcnow().isoformat(),
                            "group_id": group_id,
                            "error": None,
                            "json_path": json_backup_path,  # Fix 3: link to backup
                        }
                        # index_notebook_id already written at Step 6 — no need to repeat here
                        await asyncio.to_thread(_write_scan, scan)

                    # ── Step 16: Final state ───────────────────────────────────
                    state.update({
                        "status": final_status,
                        "group_id": group_id,
                        "sources_created": sources_created,
                        "full_card_key": full_card_key,
                        "warn_message": warn_message,
                        "error": None,
                    })
                    _write_state(thesis_name, state)
                    logger.info(
                        f"Source indexing complete for '{thesis_name}' — "
                        f"status={final_status}, group={group_id}, sources={sources_created}"
                    )

            except asyncio.CancelledError:
                # Fix 1: task.cancel() raises CancelledError — write cancelled state
                logger.info(f"Index job cancelled for '{thesis_name}'")
                state.update({
                    "status": "cancelled",
                    "error": "Run was cancelled by the user.",
                })
                _write_state(thesis_name, state)
                raise  # must re-raise so asyncio knows the task is done

            except (NLMAuthError, NLMNotInstalledError) as e:
                logger.error(f"NLM auth/install error for '{thesis_name}': {e}")
                state.update({
                    "status": "error",
                    "error": str(e),
                })
                _write_state(thesis_name, state)
                raise  # Fix 4: let batch runner detect auth failure and abort

            except Exception as e:
                logger.error(f"Source indexing failed for '{thesis_name}': {e}", exc_info=True)
                state.update({
                    "status": "error",
                    "error": str(e),
                })
                _write_state(thesis_name, state)

    finally:
        # Fix 1: clean up task reference on any exit path
        _active_tasks.pop(thesis_name, None)
        pass
        # Intentionally NOT deleting the lock from _index_locks to prevent the
        # Lock Deletion Race Condition. Idle locks consume virtually zero memory.


# ── Batch pipeline ─────────────────────────────────────────────────────────────

async def run_batch_index_sequence(
    batch_id: str,
    thesis_names: list[str],
    thesis_id: str = "",
    included_files_map: Optional[dict[str, list[str]]] = None,
) -> None:
    """
    Splits thesis_names into two halves and runs them with asyncio.TaskGroup.
    Each worker processes its half sequentially.
    """
    mid = math.ceil(len(thesis_names) / 2)
    worker_a = thesis_names[:mid]
    worker_b = thesis_names[mid:]

    batch_state = {
        "batch_id": batch_id,
        "status": "running",
        "total": len(thesis_names),
        "jobs": {t: "queued" for t in thesis_names},
        "started_at": datetime.utcnow().isoformat(),
    }
    storage.write_misc(batch_id, batch_state, thesis_id="")

    async def _worker(names: list[str]) -> None:
        for name in names:
            # Fix 2: skip folders already running from a concurrent single run
            if await is_index_running(name):
                logger.info(
                    f"Batch skipping '{name}' — already running from a single run. "
                    "Will re-check after lock is released via skip_if_done."
                )

            try:
                # skip_if_done=True: if a single run finished while we waited on
                # the lock, we skip instead of re-running and overwriting the result.
                sub_task = asyncio.create_task(
                    run_index_sequence(
                        name,
                        thesis_id=thesis_id,
                        batch_id=batch_id,
                        skip_if_done=True,
                        included_files=included_files_map.get(name) if included_files_map else None,
                    )
                )
                await sub_task
                # Fix 5: explicitly read the written status — captures "warn" correctly
                final = _read_state(name).get("status", "done")

            except asyncio.CancelledError:
                logger.info(f"Batch skipping '{name}' — run was manually cancelled.")
                batch_state["jobs"][name] = "cancelled"
                storage.write_misc(batch_id, batch_state, thesis_id="")
                continue # Local cancellation; move to next job!
                
            except Exception:
                final = "error"

            batch_state["jobs"][name] = final
            storage.write_misc(batch_id, batch_state, thesis_id="")

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_worker(worker_a))
            tg.create_task(_worker(worker_b))
        final_status = "done"
    except ExceptionGroup as eg:
        # TaskGroup wraps exceptions in ExceptionGroup
        auth_errs = [e for e in eg.exceptions if isinstance(e, (NLMAuthError, NLMNotInstalledError))]
        if auth_errs:
            final_status = "auth_error"
            # State is written below in the finally/success block
            # For auth errors, the individual worker already updated its jobs map
        else:
            logger.error(f"Batch '{batch_id}' unexpected error: {eg}", exc_info=True)
            final_status = "error"
    except asyncio.CancelledError:
        logger.warning(f"Batch '{batch_id}' was cancelled.")
        final_status = "cancelled"
        batch_state.update({
            "status": "cancelled",
            "completed_at": datetime.utcnow().isoformat(),
        })
        storage.write_misc(batch_id, batch_state, thesis_id="")
        raise
    except Exception as e:
        logger.error(f"Batch '{batch_id}' unexpected error: {e}", exc_info=True)
        final_status = "error"

    batch_state.update({
        "status": final_status,
        "completed_at": datetime.utcnow().isoformat(),
    })
    storage.write_misc(batch_id, batch_state, thesis_id="")


# ── Public status helpers ──────────────────────────────────────────────────────

def get_index_status(thesis_names: list[str]) -> list[dict]:
    """Returns current state for each thesis name."""
    result = []
    for name in thesis_names:
        state = _read_state(name)
        result.append({
            "thesis_name": name,
            "status": state.get("status", "idle"),
            "sources_uploaded": state.get("sources_uploaded", []),
            "sources_failed": state.get("sources_failed", []),
            "missing_sources": state.get("missing_sources", []),
            "error": state.get("error"),
            "warn_message": state.get("warn_message"),
            "group_id": state.get("group_id"),
            "sources_created": state.get("sources_created", 0),
            "run_count": state.get("run_count", 0),
            "last_run_at": state.get("last_run_at"),
            "batch_id": state.get("batch_id"),
            "index_notebook_id": state.get("index_notebook_id"),
        })
    return result


def get_batch_status(batch_id: str) -> dict:
    """Returns batch progress summary."""
    state = storage.read_misc(batch_id, thesis_id="") or {}
    jobs = state.get("jobs", {})
    done = sum(1 for s in jobs.values() if s in ("done", "warn"))
    error = sum(1 for s in jobs.values() if s == "error")
    return {
        "batch_id": batch_id,
        "status": state.get("status", "unknown"),
        "progress": {
            "done": done,
            "warn": sum(1 for s in jobs.values() if s == "warn"),
            "error": error,
            "total": state.get("total", len(jobs)),
        },
        "jobs": [{"thesis_name": k, "status": v} for k, v in jobs.items()],
        "started_at": state.get("started_at"),
        "completed_at": state.get("completed_at"),
    }


async def cancel_index_job(thesis_name: str) -> bool:
    """
    Cancels a running index job.

    Fix 1: calls task.cancel() on the actual asyncio.Task so execution stops.
    Simply removing the lock was wrong — the task kept running in memory.
    CancelledError is caught inside run_index_sequence which writes state=cancelled.

    Returns True if a running task was found and cancelled.
    """
    # Cancel the actual task first — this raises CancelledError inside run_index_sequence
    task = _active_tasks.get(thesis_name)
    had_task = task is not None and not task.done()
    if had_task:
        task.cancel()
        logger.info(f"cancel_index_job: task.cancel() called for '{thesis_name}'")

    # Do NOT delete the lock and do NOT write the cancelled state manually!
    # The task.cancel() above triggers the Except CancelledError block inside 
    # run_index_sequence, which will synchronously and safely write the state 
    # as its final act before exiting. This avoids the State Overwrite Race Condition!
    
    return had_task
