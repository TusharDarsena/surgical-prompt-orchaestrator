"""
NotebookLM Service
------------------
All business logic for NotebookLM automation.
No FastAPI or HTTP concerns — the router translates domain exceptions
to HTTP status codes; this layer knows nothing about HTTP.

Exception contract (router must handle):
  NLMNotInstalledError  → 503  (notebooklm-py not installed)
  NLMAuthError          → 503  (credentials missing or invalid)
  RuntimeError          → 502  (API call succeeded but returned bad data)
  All others propagate  → 500  (unexpected — let FastAPI handle)
"""

import asyncio
import json
import logging
import math
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from services import storage
from services.source_resolver import _match_thesis_name
from services.compiler_service import _render_notebooklm_prompt, _resolve_required_sources

logger = logging.getLogger(__name__)


# ── Domain exceptions ──────────────────────────────────────────────────────────

class NLMNotInstalledError(Exception):
    """notebooklm-py package is not installed."""


class NLMAuthError(Exception):
    """NotebookLM credentials are missing or invalid."""


# ── Client context manager ─────────────────────────────────────────────────────

@asynccontextmanager
async def _nlm_client():
    """
    Yields a ready NotebookLMClient for the duration of the async with block.

    Every call uses the correct pattern:
        async with await NotebookLMClient.from_storage() as client:
            ...

    This properly opens and closes the internal httpx.AsyncClient session.
    Credentials are read from disk (set by `notebooklm login`) or from the
    NOTEBOOKLM_AUTH_JSON environment variable — no re-authentication happens.

    Only wraps the INITIALIZATION phase in an error handler.
    Errors that occur INSIDE the `async with` block (e.g. upload failures,
    empty responses) propagate naturally — they are NOT credential errors
    and must NOT be wrapped with "Could not initialize NotebookLM client".
    """
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        raise NLMNotInstalledError(
            "notebooklm-py is not installed. "
            "Run: pip install 'notebooklm-py[browser]' && playwright install chromium"
        )

    # ── Phase 1: initialize the client ────────────────────────────────────────
    # Only this part gets the "could not initialize" treatment.
    try:
        client_cm = await NotebookLMClient.from_storage()
    except Exception as e:
        raise NLMAuthError(
            f"Could not initialize NotebookLM client: {e}. "
            "Run 'notebooklm login' in your terminal to authenticate, "
            "or set the NOTEBOOKLM_AUTH_JSON environment variable."
        )

    # ── Phase 2: use the client ───────────────────────────────────────────────
    # Exceptions here (upload errors, empty responses, etc.) propagate to the
    # caller unchanged — _run_sequence catches them and writes status: "error".
    async with client_cm as client:
        yield client


# ── In-memory run locks ────────────────────────────────────────────────────────
# Keyed by (chapter_id, subtopic_id). Acquired for the full duration of a run.
# Intentionally NOT persisted to disk — vanishes on server restart,
# which is what we want (no zombie locks after a crash).

_run_locks: dict[tuple[str, str], asyncio.Lock] = {}
_locks_registry_lock = asyncio.Lock()


async def _get_run_lock(chapter_id: str, subtopic_id: str) -> asyncio.Lock:
    key = (chapter_id, subtopic_id)
    async with _locks_registry_lock:
        if key not in _run_locks:
            _run_locks[key] = asyncio.Lock()
        return _run_locks[key]


async def is_run_active(chapter_id: str, subtopic_id: str) -> bool:
    """
    Public interface for the router to check whether a run lock is held.
    Keeps the lock dictionary fully encapsulated in the service layer.
    """
    lock = await _get_run_lock(chapter_id, subtopic_id)
    return lock.locked()


# ── Notebook title builder ─────────────────────────────────────────────────────

def _build_notebook_title(
    subtopic: dict,
    prefix: str = "SPO",
    override: Optional[str] = None,
) -> str:
    """
    Single source of truth for notebook title construction.
    Both single-run and batch-worker paths call this.
    """
    if override:
        return override[:100]
    number = subtopic.get("number", subtopic.get("subtopic_id", ""))
    title = subtopic.get("title", "")
    return f"{prefix} — {number} {title}"[:100]


# ── Batch ID generator ─────────────────────────────────────────────────────────

def generate_batch_id(chapter_id: str) -> str:
    """Naming convention for batch IDs lives here, not in the router."""
    return f"batch_{chapter_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"


# ── PDF size guard ─────────────────────────────────────────────────────────────

PDF_SIZE_LIMIT_MB = 5.0


async def check_pdf_sizes(validated_subtopics: list[dict]) -> list[dict]:
    """
    Resolves PDFs for every subtopic in the list and returns a list of
    oversized file dicts (empty list means all files are within the limit).

    Each returned dict has keys: subtopic_id, file, size_mb.
    """
    oversized: list[dict] = []
    for subtopic in validated_subtopics:
        source_ids = subtopic.get("source_ids", [])
        required_sources = await asyncio.to_thread(_resolve_required_sources, source_ids)
        resolved_paths = await asyncio.to_thread(_resolve_absolute_paths, required_sources)
        for entry in resolved_paths:
            size_mb = entry.get("file_size_mb")
            if size_mb is not None and size_mb > PDF_SIZE_LIMIT_MB:
                oversized.append({
                    "subtopic_id": subtopic["subtopic_id"],
                    "file": entry["file_name"],
                    "size_mb": size_mb,
                })
    return oversized


# ── Internal helpers ───────────────────────────────────────────────────────────

def _compile_prompt_data(
    chapter: dict,
    subtopic: dict,
    chapter_id: str,
    word_count: Optional[int],
    academic_style_notes: Optional[str],
) -> tuple[dict, list[dict]]:
    """
    Synchronous. Called via asyncio.to_thread — does not block the event loop.
    Compiles the prompt and resolves required sources from stored chapter data.
    """
    subtopics = chapter.get("subtopics", [])
    subtopic_id = subtopic["subtopic_id"]
    source_ids = subtopic.get("source_ids", [])

    # Previous section summary for context injection
    ids_in_order = [s["subtopic_id"] for s in subtopics]
    previous_summary = None
    if subtopic_id in ids_in_order:
        idx = ids_in_order.index(subtopic_id)
        if idx > 0:
            previous_summary = storage.read_section_summary(
                chapter_id, ids_in_order[idx - 1]
            )

    prompts = _render_notebooklm_prompt(
        chapter=chapter,
        subtopic=subtopic,
        previous_summary=previous_summary,
        word_count_override=word_count,
        academic_style_notes=academic_style_notes,
    )

    required_sources = _resolve_required_sources(source_ids)

    return prompts, required_sources


def _resolve_absolute_paths(required_sources: list[dict]) -> list[dict]:
    """
    Synchronous. Called via asyncio.to_thread.

    Extends each required_source entry with abs_path — the full local
    filesystem path notebooklm-py needs to call add_file().

    Path resolution order (first non-None wins):
      - folder_path   — written by the current rglob-based scan (drive.py)
      - level4_path   — written by the old nested scan (legacy entries)
      - level2_path   — written by the old flat scan (legacy entries)

    Thesis name matching delegates to source_resolver._match_thesis_name:
      1. Exact match — always hits after chapterization source_ids are corrected
      2. Case-insensitive fallback

    Deduplication:
      - If multiple source_ids resolve to the same PDF, upload only once
    """
    scan = storage.read_misc("drive_scan_result") or {}
    seen: set[str] = set()
    result = []

    for entry in required_sources:
        file_name = entry.get("file_name")
        if not file_name:
            continue

        thesis_name = entry.get("source_id", "")
        abs_path = None

        # Delegate thesis matching to the single authority in source_resolver
        thesis_entry = _match_thesis_name(thesis_name, scan)

        if thesis_entry:
            # folder_path (new rglob scan), level4_path (old nested), level2_path (old flat)
            folder = (
                thesis_entry.get("folder_path")
                or thesis_entry.get("level4_path")
                or thesis_entry.get("level2_path")
            )
            if folder:
                candidate = os.path.join(folder, file_name)
                if os.path.isfile(candidate):
                    abs_path = candidate
                else:
                    logger.warning(
                        f"'{file_name}' not found at '{candidate}'. "
                        "Re-run POST /drive/scan-local if files have moved."
                    )
        else:
            logger.warning(
                f"Thesis '{thesis_name}' not found in scan. "
                "Run POST /drive/scan-local first."
            )

        # Deduplicate — same PDF from multiple source_id entries
        dedup_key = abs_path if abs_path else f"unresolved::{file_name}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        file_size_mb = None
        if abs_path and os.path.isfile(abs_path):
            file_size_mb = os.path.getsize(abs_path) / (1024 * 1024)

        result.append({
            "file_name": file_name,
            "abs_path": abs_path,
            "file_size_mb": round(file_size_mb, 2) if file_size_mb is not None else None,
        })

    return result


# ── Core sequences ─────────────────────────────────────────────────────────────

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

                    # Guard against non-PDF files
                    if not file_name.lower().endswith(".pdf"):
                        failed.append({
                            "file": file_name,
                            "reason": "not a PDF — only .pdf files are uploaded automatically",
                            "failure_type": "not_pdf"
                        })
                        logger.warning(f"Skipping non-PDF file '{file_name}'")
                        continue

                    if not abs_path:
                        failed.append({
                            "file": file_name,
                            "reason": (
                                "local path could not be resolved — "
                                "run POST /drive/scan-local first"
                            ),
                            "failure_type": "unresolved"
                        })
                        logger.warning(f"No local path resolved for '{file_name}'")
                        continue

                    # Verify file exists before attempting upload
                    if not os.path.isfile(abs_path):
                        failed.append({
                            "file": file_name,
                            "reason": f"file not found at resolved path: {abs_path}",
                            "failure_type": "not_found"
                        })
                        logger.warning(f"File missing at '{abs_path}'")
                        continue

                    try:
                        await client.sources.add_file(notebook_id, abs_path, wait=True)
                        uploaded.append(file_name)
                        logger.info(f"Uploaded '{file_name}'")
                    except Exception as e:
                        failed.append({
                            "file": file_name,
                            "reason": str(e),
                            "failure_type": "api_error"
                        })
                        logger.warning(f"Upload failed for '{file_name}': {e}")

                    # Rate-limit buffer between uploads
                    await asyncio.sleep(2)

                state["sources_uploaded"] = uploaded
                state["sources_failed"] = failed
                storage.write_nlm_state(chapter_id, subtopic_id, state)

                # ── Completeness Check ─────────────────────────────────────
                resolvable = [
                    p for p in resolved_paths 
                    if p.get("abs_path") and p.get("file_name", "").lower().endswith(".pdf")
                ]
                
                # No valid PDFs found at all — path resolution failed entirely
                if not resolvable:
                    raise RuntimeError(
                        f"No uploadable PDFs found. All {len(resolved_paths)} source(s) failed "
                        f"path resolution. Failed: {failed}. "
                        "Run POST /drive/scan-local to refresh the file index."
                    )

                # Some PDFs resolved but not all uploaded successfully
                if len(uploaded) < len(resolvable):
                    missing = [
                        p["file_name"] for p in resolvable
                        if p["file_name"] not in uploaded
                    ]
                    raise RuntimeError(
                        f"Incomplete upload: {len(uploaded)}/{len(resolvable)} PDFs succeeded. "
                        f"Missing: {missing}. Aborting to avoid a response based on partial sources."
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
            notebook_title = _build_notebook_title(
                subtopic,
                prefix=notebook_title_prefix or "SPO",
            )
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


# ── Summarization ──────────────────────────────────────────────────────────────

async def suggest_summary_service(
    chapter_id: str,
    subtopic_id: str,
    subtopic: dict,
    notebook_id: str,
    save: bool,
) -> dict:
    """
    Sends a structured prompt to the existing notebook asking it to produce
    a consistency summary. Returns the response dict the router passes
    straight back to the caller.

    Raises:
        NLMNotInstalledError / NLMAuthError  — router translates to 503
        RuntimeError                          — router translates to 502
    """
    summary_prompt = (
        f"Based on the section you just wrote for subtopic "
        f"{subtopic.get('number', subtopic_id)} — {subtopic.get('title', '')}, "
        f"produce a structured consistency summary in exactly this JSON format:\n\n"
        f"{{\n"
        f'  "core_argument_made": "2-3 sentences: what was the central argument?",\n'
        f'  "key_terms_established": ["term1", "term2"],\n'
        f'  "what_next_section_must_build_on": "One sentence bridging to the next section."\n'
        f"}}\n\n"
        f"Return only the JSON. No preamble, no markdown fences."
    )

    try:
        async with _nlm_client() as client:
            result = await client.chat.ask(notebook_id, summary_prompt)
        raw_text = result.answer
    except (NLMNotInstalledError, NLMAuthError):
        raise  # router translates to 503
    except Exception as e:
        raise RuntimeError(f"NotebookLM API call failed: {e}")  # router translates to 502

    # Strip markdown fences — NLM sometimes wraps JSON despite instructions
    suggested_summary = None
    parse_error = None
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        suggested_summary = json.loads(clean)
    except (json.JSONDecodeError, ValueError) as e:
        parse_error = str(e)

    saved = False
    if save and suggested_summary and not parse_error:
        summary_record = {
            "subtopic_number": subtopic.get("number", subtopic_id),
            "subtopic_title": subtopic.get("title", ""),
            "core_argument_made": suggested_summary.get("core_argument_made", ""),
            "key_terms_established": suggested_summary.get("key_terms_established", []),
            "sources_used": [],
            "what_next_section_must_build_on": suggested_summary.get(
                "what_next_section_must_build_on"
            ),
        }
        storage.write_section_summary(chapter_id, subtopic_id, summary_record)
        saved = True

    return {
        "subtopic_id": subtopic_id,
        "suggested_summary": suggested_summary,
        "raw_response": raw_text if parse_error else None,
        "parse_error": parse_error,
        "saved": saved,
        "message": (
            "Summary saved to consistency chain."
            if saved
            else "Review the suggestion. POST with save: true to save it."
        ),
    }
