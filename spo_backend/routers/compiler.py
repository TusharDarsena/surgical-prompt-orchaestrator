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

import re
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

    # ── Build response with source metadata ────────────────────────────────
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


# ── Source file resolver ────────────────────────────────────────────────────────

def _resolve_required_sources(source_ids: list[dict]) -> list[dict]:
    """
    For each entry in source_ids, resolve the thesis name + chapter_id
    to a local filename (and Drive link if available) using the scan dictionary.
    """
    results = []
    for entry in source_ids:
        thesis_name = entry.get("source_id", "")
        chapter_id_raw = entry.get("chapter_id", "")
        source_guidance = entry.get("source_guidance", "")

        resolved = storage.resolve_source_files(thesis_name, chapter_id_raw)

        if not resolved:
            results.append({
                "source_id": thesis_name,
                "chapter_id": chapter_id_raw,
                "source_guidance": source_guidance,
                "file_name": None,
                "drive_link": None,
            })
        else:
            for r in resolved:
                results.append({
                    "source_id": thesis_name,
                    "chapter_id": r["segment"],
                    "source_guidance": source_guidance,
                    "file_name": r["file_name"],
                    "drive_link": r["drive_link"],
                })

    return results


# ── Prompt renderer ────────────────────────────────────────────────────────────

def _render_notebooklm_prompt(
    chapter: dict,
    subtopic: dict,
    previous_summary: Optional[dict],
    word_count_override: Optional[int],
    academic_style_notes: Optional[str],
) -> dict[str, str]:

    # ── Resolve dynamic values ─────────────────────────────────────────────
    subtopic_number = subtopic.get("number", "")
    subtopic_title  = subtopic.get("title", "Untitled")
    estimated_pages = subtopic.get("estimated_pages")

    if word_count_override:
        wc = word_count_override
    elif estimated_pages:
        wc = estimated_pages * 250
    else:
        wc = 1000

    position_in_argument = subtopic.get("position_in_argument", "Not specified")
    goal                 = subtopic.get("goal", "Not specified")
    target_page_count    = estimated_pages
    # ── Build source block (chapter name + source_guidance only) ──────────
    source_ids   = subtopic.get("source_ids", [])
    source_lines = []
    for src in source_ids:
        src_label = src.get("source_id", "Unknown")
        guidance  = src.get("source_guidance", "Use as evidence.")
        source_lines.append(f"- {src_label}\n  {guidance}")
    sources_block = "\n\n".join(source_lines) if source_lines else "No sources specified."

    # ── Previous section context ───────────────────────────────────────────
    prev_lines = []
    if previous_summary:
        prev_lines += [
            "# PREVIOUS SECTION CONTEXT",
            "Do NOT repeat. Build forward from what was established.",
            "",
            f"Section {previous_summary.get('subtopic_number')} established:",
            previous_summary.get("core_argument_made", ""),
        ]
        if previous_summary.get("key_terms_established"):
            prev_lines += [
                "",
                f"Use these terms consistently (do not redefine): "
                f"{', '.join(previous_summary['key_terms_established'])}",
            ]
        if previous_summary.get("what_next_section_must_build_on"):
            prev_lines += [
                "",
                "Build on:",
                previous_summary["what_next_section_must_build_on"],
            ]
        prev_lines.append("")

    prev_ctx_block = "\n".join(prev_lines)

    # ── Style notes ────────────────────────────────────────────────────────
    style_note_line = f"\n* {academic_style_notes}" if academic_style_notes else ""

    # ── Assemble prompt ────────────────────────────────────────────────────
    prompt_1 = f"""\
You are writing an academic section of a PhD dissertation in English \
literature. Your job is structural execution: build the argument exactly \
as instructed using only the provided sources.

# {subtopic_number} {subtopic_title}
* Target length: ~{wc} words
* {position_in_argument}
* {goal}{style_note_line}

# SOURCES & DEPLOYMENT STRATEGY
{sources_block}

{prev_ctx_block}\
# STRICT RULES
- Begin directly with the argument. No "In this section" openers.
- Continuous analytical paragraphs only. No bullet points, bolding, \
or subheadings within the section.
- Do not introduce outside arguments, sources, or scholars.
- Write as a scholar would: establish the claim, acknowledge what the \
existing approach achieves before critiquing it, name what the field \
loses by maintaining this pattern, and close by signalling what becomes \
possible once it is overcome."""

    # ── Assemble Stage Two prompt ──────────────────────────────────────────
    prompt_2 = f"""\
PROMPT 2 — Gemini (Stage Two: Scholarly Elaboration)
You are a scholarly editor working on a PhD dissertation in 
English literature. When given a draft section your job is 
to expand it to genuine scholarly depth without adding new 
sources, inventing citations, or padding with repetition.

Every paragraph you add must do one of these four things:
1. STEELMAN — defend what the existing approach achieves 
   before the critique lands.
2. INSTITUTIONALIZE — explain what disciplinary or structural 
   conditions produce and reproduce the pattern being diagnosed. 
   Draw only on what the sources imply.
3. CONSEQUENTIALIZE — develop what the field specifically 
   loses by maintaining this pattern.
4. PROSPECTIVE SIGNAL — gesture toward what becomes visible 
   once the limitation is overcome. Two to three sentences only.

ALWAYS:
- Preserve all citations exactly as written in the draft.
- Match or exceed the draft's academic register.
- If the draft already handles one of the four tasks well, 
  build around it rather than replacing it.

NEVER:
- Add new scholars, sources, or outside knowledge.
- Use bullet points, bolding, or subheadings.
- Let two consecutive paragraphs do the same argumentative work.
Expand this draft to {target_page_count} pages. All four tasks must be present."""

    return {"prompt_1": prompt_1, "prompt_2": prompt_2}
