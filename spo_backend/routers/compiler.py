"""
Prompt Compiler Router
----------------------
Compiles the NotebookLM writing prompt directly from chapterization data.

The chapterization JSON contains everything needed:
  - subtopic.goal            → Core Objective
  - subtopic.source_ids[]    → Focus Points (with source_guidance)
  - subtopic.position_in_argument → Scope Control
  - chapter.sources_reserved → Do Not Include
  - subtopic.estimated_pages → Word count target
  - chapter.chapter_arc      → Chapter-level context

Previous section context is preserved via the consistency chain
(storage.read_section_summary).
"""

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
            previous_summary = storage.read_section_summary(chapter_id, prev_id)

    # ── Render prompt ──────────────────────────────────────────────────────
    prompts = _render_notebooklm_prompt(
        chapter=chapter,
        subtopic=subtopic,
        previous_summary=previous_summary,
        word_count_override=word_count,
        academic_style_notes=academic_style_notes,
    )
    prompt_1 = prompts["prompt_1"]
    prompt_2 = prompts["prompt_2"]

    # ── Effective word count ──────────────────────────────────────────────
    effective_wc = word_count
    if not effective_wc and subtopic.get("estimated_pages"):
        effective_wc = subtopic["estimated_pages"] * 250

    # ── Resolve source files from local scan ───────────────────────────────
    required_sources = _resolve_required_sources(source_ids)

    # ── Warnings ───────────────────────────────────────────────────────────
    warnings = []
    if not previous_summary and ids_in_order.index(subtopic_id) > 0:
        warnings.append("No previous section summary found. Save one after writing the previous subtopic.")
    unresolved = [r for r in required_sources if r["file_name"] is None]
    if unresolved:
        warnings.append(
            f"{len(unresolved)} source(s) could not be matched to a local file. "
            "Run Scan Folder on the Source Library page or check thesis folder names."
        )

    # ── Build response ─────────────────────────────────────────────────────
    return {
        "prompt": f"{prompt_1}\n\n\n{prompt_2}",
        "prompt_1": prompt_1,
        "prompt_2": prompt_2,
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
            f"1. Check required_sources — upload those PDFs to NotebookLM. "
            f"2. Paste Prompt 1 into NotebookLM. "
            f"3. Paste Prompt 2 into Gemini with Stage One output. "
            f"4. Save draft via POST /sections/{chapter_id}/{subtopic_id}/draft. "
            f"5. Save consistency summary via POST /consistency/{chapter_id}/{subtopic_id}."
        )
    }


# ── Re-exported from service layer ────────────────────────────────────────────
# Imported here so existing callers of routers.compiler._resolve_required_sources
# and routers.compiler._render_notebooklm_prompt continue to work unchanged.

from services.compiler_service import _resolve_required_sources, _render_notebooklm_prompt  # noqa: F401