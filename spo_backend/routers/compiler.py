"""
Prompt Compiler Router
----------------------
Compiles the NotebookLM source document + writing prompt directly from
chapterization data.

The chapterization JSON contains everything needed:
  - chapter.{number,title,goal,chapter_arc,chapter_goal_statement} → source_document context
  - subtopic.{number,title,goal,position_in_argument}              → source_document context
  - subtopic.source_ids[] (source_guidance)                        → prompt_1 instructions

Output is now split in two, per the source/prompt decoupling
(see services/compiler_service.py header for the full rationale):
  - source_document → uploaded to NotebookLM as a text source (context only)
  - prompt_1        → pasted into NotebookLM chat (instruction only)

Previous section summaries are no longer auto-included anywhere — that
data lives outside the chapterization JSON and is pasted manually into
the source document's placeholder section. storage.read_section_summary
is still consulted only to decide whether to surface a reminder warning.
"""

import asyncio
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from services import storage

router = APIRouter(prefix="/compile", tags=["Prompt Compiler"])


# ── NotebookLM Prompt (direct from chapterization) ────────────────────────────

@router.get(
    "/notebooklm-prompt/{chapter_id}/{subtopic_id}",
    summary="Compile NotebookLM prompt directly from chapterization data"
)
def compile_notebooklm_prompt(
    chapter_id: str,
    subtopic_id: str,
    word_count: Optional[int] = Query(default=None),
    academic_style_notes: Optional[str] = Query(default=None),
    thesis_id: str = Query(""),
):
    """
    Builds the NotebookLM writing prompt from the stored chapterization data.
    No task.md required — source_guidance from the chapterization JSON
    replaces the old Architect → task.md pipeline entirely.
    """
    # ── Load chapter ───────────────────────────────────────────────────────
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    # ── Load subtopic ──────────────────────────────────────────────────────
    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Subtopic '{subtopic_id}' not found. "
                f"Available: {[s['subtopic_id'] for s in subtopics]}"
            )
        )

    # ── Validate source_ids exist ──────────────────────────────────────────
    source_ids = subtopic.get("source_ids", [])
    if not source_ids:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Subtopic '{subtopic_id}' has no source_ids. "
                "Re-import the chapterization JSON with source_ids for each subtopic."
            )
        )

    # ── Previous section summary ───────────────────────────────────────────
    previous_summary = None
    ids_in_order = [s["subtopic_id"] for s in subtopics]
    if subtopic_id in ids_in_order:
        idx = ids_in_order.index(subtopic_id)
        if idx > 0:
            prev_id = ids_in_order[idx - 1]
            previous_summary = storage.read_section_summary(chapter_id, prev_id, thesis_id=thesis_id)

    # ── Render source document + prompts ────────────────────────────────────
    rendered = _render_notebooklm_prompt(
        chapter=chapter,
        subtopic=subtopic,
        previous_summary=previous_summary,
        word_count_override=word_count,
        academic_style_notes=academic_style_notes,
    )
    source_document = rendered["source_document"]
    prompt_1 = rendered["prompt_1"]

    # ── Effective word count ──────────────────────────────────────────────
    effective_wc = word_count
    if not effective_wc:
        effective_wc = 1500

    # ── Resolve source files from local scan ───────────────────────────────
    required_sources = _resolve_required_sources(source_ids, thesis_id=thesis_id)

    # ── Warnings ───────────────────────────────────────────────────────────
    warnings = []
    if not previous_summary and ids_in_order.index(subtopic_id) > 0:
        warnings.append(
            "No previous section summary found in storage. Paste it manually into the "
            "[PASTE PREVIOUS SECTION SUMMARY HERE] placeholder in source_document before uploading."
        )
    unresolved = [r for r in required_sources if r["file_name"] is None]
    if unresolved:
        warnings.append(
            f"{len(unresolved)} source(s) could not be matched to a local file. "
            "Run Scan Folder on the Source Library page or check thesis folder names."
        )

    # ── Build response ─────────────────────────────────────────────────────
    return {
        "source_document": source_document,
        "prompt_1": prompt_1,
        "meta": {
            "chapter": f"{chapter['number']} — {chapter['title']}",
            "subtopic": f"{subtopic['number']} — {subtopic['title']}",
            "previous_section_included": previous_summary is not None,
            "previous_section": (
                f"{previous_summary.get('subtopic_number')} — {previous_summary.get('subtopic_title')}"
                if previous_summary else None
            ),
            "required_sources": required_sources,
            "source_count": len(source_ids),
            "word_count_target": effective_wc,
            "warnings": warnings,
        },
        "next_step": (
            f"1. Check required_sources — upload those PDFs to NotebookLM as sources. "
            f"2. Upload source_document to NotebookLM as an additional text source "
            f"(paste in the previous section summary first if you have one). "
            f"3. Paste Prompt 1 into the NotebookLM chat box. "
            f"4. Save draft via POST /sections/{chapter_id}/{subtopic_id}/draft. "
            f"5. Save consistency summary via POST /consistency/{chapter_id}/{subtopic_id}."
        )
    }


# ── Summary Prompt (for NLM consistency message) ─────────────────────────────

@router.get(
    "/summary-prompt/{chapter_id}/{subtopic_id}",
    summary="Get the NLM summary request message for a subtopic"
)
def get_summary_prompt(
    chapter_id: str,
    subtopic_id: str,
    thesis_id: str = Query(""),
):
    """
    Returns the message to paste into the NotebookLM notebook after the draft
    is written. NLM responds in plain text; the user pastes that response into
    Card 04 on the Write Section page, which saves it as core_argument_made
    in the consistency chain.
    """
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic '{subtopic_id}' not found."
        )

    try:
        prompt_text = render_summary_prompt(subtopic)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "subtopic_number": subtopic.get("number", ""),
        "subtopic_title": subtopic.get("title", ""),
        "summary_prompt": prompt_text,
    }


# ── Chapter Source Map ────────────────────────────────────────────────────────

@router.get(
    "/chapter-source-map/{chapter_id}",
    summary="Get a deduplicated map of chapter sources"
)
async def chapter_source_map(
    chapter_id: str,
    thesis_id: str = Query(""),
):
    """
    Returns a deduplicated list of source mappings for the entire chapter.
    Delegates to compiler_service to avoid business logic in the router,
    wrapped in asyncio.to_thread to prevent blocking the event loop with
    synchronous file operations.
    """
    from services.compiler_service import get_chapter_source_map
    result = await asyncio.to_thread(get_chapter_source_map, chapter_id, thesis_id)
    return result


# ── Re-exported from service layer ─────────────────────────────────────────────────────
# Imported here so existing callers of routers.compiler._resolve_required_sources
# and routers.compiler._render_notebooklm_prompt continue to work unchanged.

from services.compiler_service import _resolve_required_sources, _render_notebooklm_prompt, render_summary_prompt, get_chapter_source_map  # noqa: F401