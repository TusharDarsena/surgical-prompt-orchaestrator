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
    """
    Renders the two-stage academic writing prompt
    (Stage One for NotebookLM, Stage Two for Gemini) with all placeholder
    fields dynamically filled from the chapterization data.

    Returns a dict with keys 'prompt_1' and 'prompt_2'.
    """

    # ── Resolve dynamic values ─────────────────────────────────────────────
    subtopic_title = subtopic.get("title", "Untitled")
    estimated_pages = subtopic.get("estimated_pages")

    if word_count_override:
        wc = word_count_override
    elif estimated_pages:
        wc = estimated_pages * 250  # ~250 words per page
    else:
        wc = None

    word_count_str = f"approximately {wc} words" if wc else "as appropriate for the section"
    position_in_argument = subtopic.get("position_in_argument", "Not specified")
    chapter_arc = chapter.get("chapter_arc", "Not specified")
    goal = subtopic.get("goal", "Not specified")
    target_page_count = estimated_pages if estimated_pages else "5–7"

    # ── Build source entries ───────────────────────────────────────────────
    source_ids = subtopic.get("source_ids", [])
    source_lines = []
    for src in source_ids:
        src_label = src.get("source_id", "Unknown")
        chapter_ref = src.get("chapter_id", "")
        guidance = src.get("source_guidance", "Use as evidence.")
        source_lines.append(f"Source: {src_label}")
        source_lines.append(f"Relevant section: {chapter_ref}")
        source_lines.append(f"How to use it: {guidance}")
        source_lines.append("")

    sources_block = "\n".join(source_lines).rstrip() if source_lines else "No sources specified."

    # ── Previous section context (injected before Prompt 1 text) ───────────
    prev_ctx_lines = []
    if previous_summary:
        prev_ctx_lines += [
            "=" * 50,
            "PREVIOUS SECTION CONTEXT — Do NOT repeat. Build forward.",
            "=" * 50,
            "",
            f"Previous section ({previous_summary.get('subtopic_number')}) established:",
            previous_summary.get("core_argument_made", ""),
            "",
        ]
        if previous_summary.get("key_terms_established"):
            prev_ctx_lines += [
                f"Use these terms consistently (do not redefine): "
                f"{', '.join(previous_summary['key_terms_established'])}",
                "",
            ]
        if previous_summary.get("what_next_section_must_build_on"):
            prev_ctx_lines += [
                "Build on:",
                previous_summary["what_next_section_must_build_on"],
                "",
            ]

    prev_ctx_block = "\n".join(prev_ctx_lines)

    # ── Do Not Include (reserved sources) ──────────────────────────────────
    reserved = chapter.get("sources_reserved_for_later_chapters", [])
    reserved_lines = []
    if reserved:
        reserved_lines.append("DO NOT INCLUDE:")
        for item in reserved:
            src_name = item.get("source_id", "Unknown source")
            reason = item.get("reason", "Reserved for later chapters.")
            reserved_lines.append(f"  ✗ {src_name}: {reason}")
        reserved_lines.append("")
    reserved_block = "\n".join(reserved_lines)

    # ── Style notes ────────────────────────────────────────────────────────
    style_note_line = f"\nSTYLE NOTES: {academic_style_notes}" if academic_style_notes else ""

    # ── Assemble Stage One prompt ───────────────────────────────────────────
    prompt_1 = f"""\
PROMPT 1 — NotebookLM (Stage One: Structural Execution)

You are writing an academic section of a PhD dissertation in English
literature. Your job in this prompt is structural execution only —
building the argument correctly from the sources provided.

SECTION DETAILS:
Title: {subtopic_title}
Target length: {word_count_str}
Position in chapter: {position_in_argument}

CHAPTER ARC CONTEXT:
{chapter_arc}

YOUR SPECIFIC GOAL FOR THIS SECTION:
{goal}

SOURCES AND HOW TO USE THEM:
{sources_block}

{prev_ctx_block}\
{reserved_block}\
WRITING RULES:
- Begin directly with the argument. No introductory throat-clearing.
- Every claim must be anchored in the sources listed above.
- Use sources as evidence for your argument. Do not summarize them.
- Academic prose only. No bullet points, no bold text, no headers
  within the section.
- Do not introduce arguments, sources, or scholars not listed above.
- Do not use phrases like "this section will" or "as we shall see."
- Produce continuous analytical paragraphs.{style_note_line}

STRUCTURAL REQUIREMENT:
Your section must move through these three registers in order:

1. State the problem or claim with precision and demonstrate
   it through evidence from the sources.

2. Steelman — spend one full paragraph acknowledging what the
   pattern you are critiquing achieves before showing its limit.
   Use the sources to ground this.

3. Consequentialize — explain specifically what this pattern
   costs the field. Name the consequence for feminist
   historiography / postcolonial studies [adjust per chapter].

4. Prospective signal — two to three sentences only, gesturing
   toward what becomes possible once this limitation is addressed.

CRITICAL: All four registers must be present in the output.
Do not omit any."""

    # ── Assemble Stage Two prompt ──────────────────────────────────────────
    prompt_2 = f"""\
PROMPT 2 — Gemini (Stage Two: Scholarly Elaboration)

Below is a draft of an academic section from a PhD dissertation.
The argument is structurally correct but underdeveloped. Your job
is to revise and expand it to {target_page_count} pages of
genuine scholarly depth. You may not add new sources or citations.
You may not pad with repetition. Every additional sentence must
perform one of the four scholarly operations listed below.

DRAFT TO REVISE:
[PASTE STAGE ONE OUTPUT HERE]

THE FOUR SCHOLARLY OPERATIONS — apply all four, in any order
that serves the argument:

OPERATION 1 — STEELMAN:
Spend one full paragraph genuinely defending the value of what
you are critiquing before showing its limitation. This is not
concession — it is intellectual honesty that makes the subsequent
critique more credible.

OPERATION 2 — INSTITUTIONALIZE:
This is the
operation the draft cannot produce on its own.
Name one structural or disciplinary reason why the pattern you
are diagnosing persists. Do not just show that it exists — explain
what institutional conditions produce and reproduce it. Draw only
on what the sources imply, not on outside claims.

OPERATION 3 — CONSEQUENTIALIZE:
Take your strongest claim and spend a full paragraph on its
specific consequences for the field (e.g. feminist historiography /
postcolonial studies / Indian English literary criticism). Do not
restate the claim — develop what it costs the field that this
pattern exists.

OPERATION 4 — PROSPECTIVE SIGNAL:
In your closing paragraph, write two to three sentences that
gesture toward what becomes analytically visible once this
limitation is overcome. Do not develop the full argument —
that belongs to later chapters. Create intellectual momentum
only.

WRITING RULES:
- Preserve all source citations from the draft exactly as written.
- Do not introduce new scholars, statistics, or outside knowledge.
- No bullet points, no bold text, no subheadings.
- Every new paragraph must be doing new argumentative work —
  not restating what the previous paragraph already established.
- Academic register throughout. Read the draft's register and
  match or exceed it.
- If a passage in the draft is already doing one of the four
  operations well, keep it and build around it rather than
  replacing it."""

    return {"prompt_1": prompt_1, "prompt_2": prompt_2}
