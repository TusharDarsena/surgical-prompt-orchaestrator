"""
Compiler Service
----------------
Pure business logic for prompt compilation and source resolution.
No FastAPI or HTTP concerns — zero imports from routers/.

Extracted from routers/compiler.py so that services/notebooklm_service.py
can import these functions without reversing the dependency direction
(services → routers is forbidden).

routers/compiler.py re-exports these under the same names so every existing
call-site outside the service layer remains unchanged.
"""

from typing import Optional
from services import storage


# ── Source file resolver ───────────────────────────────────────────────────────

def _resolve_required_sources(source_ids: list[dict]) -> list[dict]:
    """
    For each entry in source_ids, resolve the thesis name + chapter_id
    to a local filename (and Drive link if available) using the scan dictionary.

    Loads drive_scan_result once per call — callers in a loop should pass
    a pre-loaded scan dict if they need to avoid repeated disk reads.
    """
    results = []
    # Load the scan once — avoids N+1 disk reads of drive_scan_result.json
    scan = storage.read_misc("drive_scan_result") or {}
    for entry in source_ids:
        thesis_name = entry.get("source_id", "")
        chapter_id_raw = entry.get("chapter_id", "")
        source_guidance = entry.get("source_guidance", "")

        resolved = storage.resolve_source_files(thesis_name, chapter_id_raw, scan=scan)

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

    # Stage 2 length instruction — use pages if available, fall back to words
    if estimated_pages:
        stage2_length = f"{estimated_pages} pages"
    else:
        stage2_length = f"{wc} words"

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

    # ── Assemble Prompt 1 ──────────────────────────────────────────────────
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

    # ── Assemble Prompt 2 ──────────────────────────────────────────────────
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
Expand this draft to {stage2_length}. All four tasks must be present."""

    return {"prompt_1": prompt_1, "prompt_2": prompt_2}
