"""
Compiler Service
----------------
Pure business logic for prompt compilation and source resolution.
No FastAPI or HTTP concerns -- zero imports from routers/.

Extracted from routers/compiler.py so that services/notebooklm_service.py
can import these functions without reversing the dependency direction
(services -> routers is forbidden).

routers/compiler.py re-exports these under the same names so every existing
call-site outside the service layer remains unchanged.
"""

import re
from typing import Optional
from services import storage


# -- Source file resolver -------------------------------------------------------

def _resolve_required_sources(source_ids: list[dict]) -> list[dict]:
    """
    For each entry in source_ids, resolve the thesis name + chapter_id
    to a filename, Drive link, and Drive file ID.

    Primary path: source_resolver looks up source records by scan_key --
    Drive file IDs come directly from source records (no local scan needed).
    Fallback: scan dict (drive_scan_result.json) for legacy groups.
    """
    results = []
    # Load the scan once as fallback -- source_resolver uses it only for legacy groups
    scan = storage.read_misc("drive_scan_result", thesis_id="") or {}
    for entry in source_ids:
        thesis_name = entry.get("source_id", "")
        chapter_id_raw = entry.get("chapter_id", "")

        resolved = storage.resolve_source_files(thesis_name, chapter_id_raw, scan=scan)

        if not resolved:
            results.append({
                "source_id": thesis_name,
                "chapter_id": chapter_id_raw,
                "file_name": None,
                "drive_link": None,
                "drive_file_id": None,
            })
        else:
            for r in resolved:
                results.append({
                    "source_id": thesis_name,
                    "chapter_id": r["segment"],
                    "file_name": r["file_name"],
                    "drive_link": r["drive_link"],
                    "drive_file_id": r.get("drive_file_id"),
                })

    return results


# -- Prompt renderer -----------------------------------------------------------

def _render_notebooklm_prompt(
    chapter: dict,
    subtopic: dict,
    previous_summary: Optional[dict],
    word_count_override: Optional[int],
    academic_style_notes: Optional[str],
) -> dict[str, str]:

    # -- Resolve dynamic values ------------------------------------------------
    subtopic_number = subtopic.get("number", "")
    subtopic_title  = subtopic.get("title", "Untitled")

    if word_count_override:
        wc = word_count_override
    else:
        wc = 1500

    position_in_argument = subtopic.get("position_in_argument", "Not specified")
    goal                 = subtopic.get("goal", "Not specified")

    # -- Build source block (key_claim preferred; chapter_id context added) -----
    source_ids   = subtopic.get("source_ids", [])
    source_lines = []
    for src in source_ids:
        src_label = src.get("source_id", "Unknown")
        chapter_ref = src.get("chapter_id", "")
        key_claim = src.get("key_claim", "Use as evidence.")
        label = f"{src_label} [{chapter_ref}]" if chapter_ref else src_label
        source_lines.append(f"- {label}: {key_claim}")
    sources_block = "\n".join(source_lines) if source_lines else "No sources specified."

    # -- Chapter context (first 2 sentences of chapter_arc) -------------------
    chapter_arc_full = chapter.get("chapter_arc", "")
    sentences = re.split(r"(?<=[.!?])\s+", chapter_arc_full.strip())
    chapter_context = " ".join(sentences[:2]) if sentences else ""

    if chapter_context:
        chapter_ctx_block = (
            "\n# CHAPTER CONTEXT\n"
            f"{chapter_context}\n"
        )
    else:
        chapter_ctx_block = ""

    # -- Argument structure brief ----------------------------------------------
    # In the new JSON format, argument_structure is a list[str] (one entry per phase).
    # In legacy format it may be a plain string. Handle both.
    argument_structure = subtopic.get("argument_structure", "")

    if isinstance(argument_structure, list):
        # New format: join phases with blank lines for readability
        arg_structure_text = "\n\n".join(argument_structure)
    else:
        arg_structure_text = argument_structure  # legacy plain string

    if arg_structure_text:
        arg_structure_block = (
            "\n# ARGUMENT STRUCTURE\n"
            f"{arg_structure_text}\n"
        )
    else:
        arg_structure_block = ""

    # -- Style notes -----------------------------------------------------------
    if academic_style_notes:
        style_note_line = f"\n* Style notes: {academic_style_notes}"
    else:
        style_note_line = ""

    # -- Previous section context ----------------------------------------------
    prev_lines = []
    if previous_summary:
        prev_lines += [
            "# PREVIOUS SECTION CONTEXT",
            "Do NOT repeat. Do not reopen arguments already settled. Build forward.",
            "",
            f"Section {previous_summary.get('subtopic_number')} established:",
            previous_summary.get("core_argument_made", ""),
        ]
        if previous_summary.get("key_terms_established"):
            prev_lines += [
                "",
                f"Terms already defined -- use consistently, do not redefine: "
                f"{', '.join(previous_summary['key_terms_established'])}",
            ]
        if previous_summary.get("sources_used"):
            prev_lines += [
                "",
                f"Scholars already named -- do not reintroduce them as if new: "
                f"{', '.join(previous_summary['sources_used'])}",
            ]
        if previous_summary.get("what_next_section_must_build_on"):
            prev_lines += [
                "",
                "This section must build on:",
                previous_summary["what_next_section_must_build_on"],
            ]
        prev_lines.append("")

    prev_ctx_block = "\n".join(prev_lines)

    # -- Assemble Prompt 1 -----------------------------------------------------
    prompt_1_parts = [
        "You are a research assistant synthesizing grounded claims from uploaded "
        "academic sources into a PhD dissertation section. Every claim you make "
        "must be traceable to the provided sources. Do not introduce scholars, "
        "frameworks, or arguments that do not appear in the uploaded source texts.",
        chapter_ctx_block,
        f"# SECTION {subtopic_number}: {subtopic_title}",
        f"* Target length: ~{wc} words",
        f"* Section goal: {goal}",
        f"* Role in chapter argument: {position_in_argument}{style_note_line}",
        "",
        "# SOURCES",
        sources_block,
        arg_structure_block,
        prev_ctx_block,
        "# STRICT RULES",
        '- Begin directly with the argument. No "In this section" or "This section will" openers.',
        "- Continuous analytical paragraphs only. No bullet points, bolding, or subheadings.",
        "- Cite every claim with a bracketed inline citation tied to its source, "
        "e.g. [Source Name, Chapter X]. Every paragraph must contain at least one citation.",
        "- Name only scholars and theoretical concepts that appear explicitly in the "
        "uploaded source texts. If a theorist is not named in the source, do not "
        "introduce them -- refer to the argument, not the theorist.",
        "- Each paragraph makes one distinct argumentative move. No two paragraphs restate the same point.",
        "- The closing sentence must state the intellectual question this section's "
        'argument opens -- the question that becomes askable because of what was '
        'established here. Do NOT write "the next section will..." or "as this '
        'analysis moves forward..." State it as a claim in motion.',
    ]
    prompt_1 = "\n".join(prompt_1_parts)

    # -- Prompt 2: Stage 2 Gemini expansion removed ----------------------------
    # After reviewing the NLM draft, ask NLM for a plain-text summary using
    # render_summary_prompt(), then save it via:
    # POST /consistency/{chapter_id}/{subtopic_id}
    return {"prompt_1": prompt_1}


# -- Summary prompt renderer ---------------------------------------------------

def render_summary_prompt(subtopic: dict) -> str:
    """
    Reads prompts/generate_subtopic_summary.txt and injects the subtopic's
    number and title. The returned string is the message the user pastes into
    the NLM notebook after the draft is written, asking NLM to summarise what
    it argued. The plain-text response becomes core_argument_made in the
    consistency chain.
    """
    import pathlib
    template_path = pathlib.Path("prompts/generate_subtopic_summary.txt")
    if not template_path.exists():
        raise FileNotFoundError("prompts/generate_subtopic_summary.txt not found")
    template = template_path.read_text(encoding="utf-8")
    return (
        template
        .replace("{subtopic_number}", subtopic.get("number", ""))
        .replace("{subtopic_title}", subtopic.get("title", ""))
    )
