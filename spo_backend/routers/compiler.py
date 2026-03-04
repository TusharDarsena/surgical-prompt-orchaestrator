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
):
    """
    Builds the NotebookLM writing prompt from the stored chapterization data.
    No task.md required — source_guidance from the chapterization JSON
    replaces the old Architect → task.md pipeline entirely.
    """
    # ── Load chapter ───────────────────────────────────────────────────────
    chapter = storage.read_chapter(chapter_id)
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

    # ── Previous section summary (preserved from old pipeline) ─────────────
    previous_summary = None
    ids_in_order = [s["subtopic_id"] for s in subtopics]
    if subtopic_id in ids_in_order:
        idx = ids_in_order.index(subtopic_id)
        if idx > 0:
            prev_id = ids_in_order[idx - 1]
            previous_summary = storage.read_section_summary(chapter_id, prev_id)

    # ── Render prompt ──────────────────────────────────────────────────────
    prompt = _render_notebooklm_prompt(
        chapter=chapter,
        subtopic=subtopic,
        previous_summary=previous_summary,
        word_count_override=word_count,
        academic_style_notes=academic_style_notes,
    )

    # ── Build response with source metadata ────────────────────────────────
    return {
        "prompt": prompt,
        "meta": {
            "chapter": f"{chapter['number']} — {chapter['title']}",
            "subtopic": f"{subtopic['number']} — {subtopic['title']}",
            "previous_section_included": previous_summary is not None,
            "previous_section": (
                f"{previous_summary.get('subtopic_number')} — {previous_summary.get('subtopic_title')}"
                if previous_summary else None
            ),
            "required_sources": [
                {
                    "source_id": s.get("source_id", ""),
                    "chapter_id": s.get("chapter_id", ""),
                }
                for s in source_ids
            ],
            "source_count": len(source_ids),
        },
        "next_step": (
            f"1. Upload the relevant PDFs to NotebookLM. "
            f"2. Paste the prompt. "
            f"3. After approving draft: POST /consistency/{chapter_id}/{subtopic_id}"
        )
    }


# ── Prompt renderer ────────────────────────────────────────────────────────────

def _render_notebooklm_prompt(
    chapter: dict,
    subtopic: dict,
    previous_summary: Optional[dict],
    word_count_override: Optional[int],
    academic_style_notes: Optional[str],
) -> str:
    L = []
    subtopic_ref = f"{subtopic.get('number', '')} — {subtopic.get('title', '')}"

    # ── Opening instruction ────────────────────────────────────────────────
    L += [
        f"Write section {subtopic_ref} of the thesis.",
        "",
        "Follow the blueprint below STRICTLY.",
        "Use ONLY the uploaded PDF sources. Do not draw on outside knowledge.",
        "Do not invent citations, statistics, or historical claims.",
        "",
    ]

    # ── Word count target ──────────────────────────────────────────────────
    estimated_pages = subtopic.get("estimated_pages")
    if word_count_override:
        wc = word_count_override
    elif estimated_pages:
        wc = estimated_pages * 250  # ~250 words per page
    else:
        wc = None

    if wc:
        L += [f"TARGET LENGTH: approximately {wc} words.", ""]

    # ── Previous section context (preserved verbatim from old pipeline) ─────
    if previous_summary:
        L += [
            "=" * 50,
            "PREVIOUS SECTION CONTEXT — Do NOT repeat. Build forward.",
            "=" * 50,
            "",
            f"Previous section ({previous_summary.get('subtopic_number')}) established:",
            previous_summary["core_argument_made"],
            "",
        ]
        if previous_summary.get("key_terms_established"):
            L += [
                f"Use these terms consistently (do not redefine): "
                f"{', '.join(previous_summary['key_terms_established'])}",
                "",
            ]
        if previous_summary.get("what_next_section_must_build_on"):
            L += ["Build on:", previous_summary["what_next_section_must_build_on"], ""]

    # ── Chapter arc context ────────────────────────────────────────────────
    chapter_arc = chapter.get("chapter_arc")
    if chapter_arc:
        L += [
            "=" * 50,
            "CHAPTER ARC",
            "(This section is part of a larger chapter argument. "
            "Stay within the role assigned below.)",
            "=" * 50,
            "",
            f"CHAPTER {chapter['number']}: {chapter['title']}",
            "",
            chapter_arc,
            "",
        ]

    # ── Core objective (from subtopic goal) ────────────────────────────────
    L += [
        "=" * 50,
        "WRITING BLUEPRINT",
        "=" * 50,
        "",
        f"CORE OBJECTIVE: {subtopic['goal']}",
        "",
    ]

    # ── Position in argument (scope control) ───────────────────────────────
    if subtopic.get("position_in_argument"):
        L += [
            "POSITION IN CHAPTER ARC:",
            subtopic["position_in_argument"],
            "",
        ]

    # ── Focus points (from source_ids with source_guidance) ────────────────
    source_ids = subtopic.get("source_ids", [])
    if source_ids:
        L += ["FOCUS POINTS (cover all, using the corresponding source):"]
        for i, src in enumerate(source_ids, 1):
            src_label = src.get("source_id", f"Source {i}")
            chapter_ref = src.get("chapter_id", "")
            guidance = src.get("source_guidance", "Use as evidence.")

            label = f"[{src_label}"
            if chapter_ref:
                label += f" — {chapter_ref}"
            label += "]"

            L.append(f"  {i}. {label}")
            L.append(f"     {guidance}")
            L.append("")

    # ── Do Not Include (from sources_reserved_for_later_chapters) ──────────
    reserved = chapter.get("sources_reserved_for_later_chapters", [])
    if reserved:
        L += ["DO NOT INCLUDE:"]
        for item in reserved:
            src_name = item.get("source_id", "Unknown source")
            reason = item.get("reason", "Reserved for later chapters.")
            L.append(f"  ✗ {src_name}: {reason}")
        L.append("")

    # ── Writing rules (preserved verbatim from old pipeline) ───────────────
    L += [
        "=" * 50,
        "WRITING RULES",
        "=" * 50,
        "",
        "• Begin directly with the argument. No 'In this section we will...' openers.",
        "• Every claim must be evidenced from the uploaded sources.",
        "• Academic register. Analytical, not descriptive.",
        "• Prose paragraphs only — no bullet points in the output.",
        "• Do not summarise sources. Use them as evidence.",
        "• Do not introduce arguments outside the Focus Points.",
    ]

    if academic_style_notes:
        L += ["", f"STYLE NOTES: {academic_style_notes}"]

    return "\n".join(L)