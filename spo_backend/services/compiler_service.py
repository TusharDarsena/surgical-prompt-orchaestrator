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

── Source/Prompt split ────────────────────────────────────────────────────
NotebookLM receives two distinct things:

  1. source_document — uploaded as a regular text source alongside the
     PDFs. Carries CONTEXT: chapter framing, subtopic framing, and the
     previous-subtopic summary (pasted in manually — that data lives
     outside the chapterization JSON). NotebookLM treats this as
     grounding material, not as an instruction to execute.

  2. prompt_1 — pasted into the NotebookLM chat box. Carries
     INSTRUCTION only: per-source deployment guidance and the strict
     writing rules. Nothing here describes what the chapter/subtopic
     "is" — only what to do with the sources.

To keep this split easy to re-template later, the work is broken into
two stages that don't know about each other's wording:

  Stage A — _build_source_doc_fields() / _build_prompt_fields()
            Pure data assembly. Decides WHICH chapterization fields go
            into the source document vs. the prompt. No string literals
            of dissertation prose live here.

  Stage B — _render_source_document() / _render_prompt_1()
            Pure templating. Takes the field dict from Stage A and
            produces final text. All prose/wording changes happen here
            ONLY — Stage A never needs to change when the template does.

When a new prompt template is supplied, only the Stage B render
functions (and possibly the *_keys constants) should need editing.
"""

from typing import Optional
from services import storage


# ── Source file resolver ───────────────────────────────────────────────────────

def _resolve_required_sources(source_ids: list[dict], thesis_id: str = "") -> list[dict]:
    """
    For each entry in source_ids, resolve the thesis name + chapter_id
    to a filename, Drive link, and Drive file ID.

    Primary path: source_resolver looks up source records by scan_key —
    Drive file IDs come directly from source records (no local scan needed).
    Fallback: scan dict (drive_scan_result.json) for legacy groups.
    """
    results = []
    # Load the scan once as fallback — source_resolver uses it only for legacy groups
    scan = storage.read_misc("drive_scan_result", thesis_id="") or {}
    for entry in source_ids:
        thesis_name = entry.get("source_id", "")
        chapter_id_raw = entry.get("chapter_id", "")
        source_guidance = entry.get("source_guidance", "")

        resolved = storage.resolve_source_files(thesis_name, chapter_id_raw, scan=scan, thesis_id=thesis_id)

        if not resolved:
            results.append({
                "source_id": thesis_name,
                "chapter_id": chapter_id_raw,
                "source_guidance": source_guidance,
                "file_name": None,
                "drive_link": None,
                "drive_file_id": None,
            })
        else:
            for r in resolved:
                results.append({
                    "source_id": thesis_name,
                    "chapter_id": r["segment"],
                    "source_guidance": source_guidance,
                    "file_name": r["file_name"],
                    "drive_link": r["drive_link"],
                    "drive_file_id": r.get("drive_file_id"),
                })

    return results


# ── Stage A: data assembly ─────────────────────────────────────────────────────
# Decides WHICH chapterization fields go where. No prose wording lives here.

# Field routing is explicit and declarative so it's obvious at a glance
# what ends up in the source doc vs. the prompt — and so adding/removing
# a field later is a one-line change, not a hunt through f-strings.

SOURCE_DOC_CHAPTER_KEYS = ["number", "title", "goal", "chapter_arc", "chapter_goal_statement"]
SOURCE_DOC_SUBTOPIC_KEYS = ["number", "title", "goal", "position_in_argument"]


def _build_source_doc_fields(chapter: dict, subtopic: dict) -> dict:
    """
    Assemble the data that goes into the NotebookLM *source document*
    (context only — chapter framing + subtopic framing). The previous
    section summary is NOT included here: that data lives outside the
    chapterization JSON and is pasted in manually, so the renderer just
    leaves a clearly marked placeholder for it.
    """
    all_subtopics_data = []
    for s in chapter.get("subtopics", []):
        all_subtopics_data.append({k: s.get(k) for k in SOURCE_DOC_SUBTOPIC_KEYS})

    return {
        "chapter": {k: chapter.get(k) for k in SOURCE_DOC_CHAPTER_KEYS},
        "subtopic": {k: subtopic.get(k) for k in SOURCE_DOC_SUBTOPIC_KEYS},
        "all_subtopics": all_subtopics_data,
    }


def _build_prompt_fields(
    subtopic: dict,
    word_count_override: Optional[int],
    academic_style_notes: Optional[str],
) -> dict:
    """
    Assemble the data that goes into the NotebookLM *prompt* (instruction
    only — source deployment guidance + strict rules). Deliberately
    excludes chapter/subtopic framing, which now lives in the source doc.
    """
    if word_count_override:
        wc = word_count_override
    else:
        wc = 1500

    source_ids = subtopic.get("source_ids", [])

    return {
        "word_count": wc,
        "academic_style_notes": academic_style_notes,
        "source_ids": source_ids,
        "subtopic_number": subtopic.get("number", ""),
        "subtopic_title": subtopic.get("title", "Untitled"),
    }


# ── Stage B: templating ────────────────────────────────────────────────────────
# All prose/wording lives here. Swap these out when the template changes —
# Stage A above should not need to change alongside them.

def _render_source_document(fields: dict) -> str:
    """
    Renders the NotebookLM source document (context-only).
    Uploaded as a text source in NotebookLM, NOT pasted as the prompt.
    """
    ch = fields["chapter"]
    st = fields["subtopic"]
    all_st = fields.get("all_subtopics", [])

    lines = [
        "# CHAPTER CONTEXT",
        f"Chapter {ch.get('number', '')}: {ch.get('title', 'Untitled')}",
        "",
        "## Chapter Goal",
        ch.get("goal") or "Not specified",
        "",
        "## Chapter Arc",
        ch.get("chapter_arc") or "Not specified",
        "",
        "## Chapter Goal Statement",
        ch.get("chapter_goal_statement") or "Not specified",
        "",
        "# PREVIOUS SECTION SUMMARY",
        "[PASTE PREVIOUS SECTION SUMMARY HERE — not part of the chapterization JSON]",
        "",
        "# CHAPTER OUTLINE",
    ]

    for s_data in all_st:
        lines.extend([
            f"## Subtopic {s_data.get('number', '')}: {s_data.get('title', 'Untitled')}",
            f"**Goal**: {s_data.get('goal') or 'Not specified'}",
            f"**Position in Argument**: {s_data.get('position_in_argument') or 'Not specified'}",
            "",
        ])

    return "\n".join(lines)


def _render_prompt_1(fields: dict) -> str:
    """
    Renders Prompt 1 (instruction-only — pasted into NotebookLM chat).
    No chapter/subtopic framing here; NotebookLM gets that from the
    source document instead.
    """
    wc = fields["word_count"]
    academic_style_notes = fields["academic_style_notes"]
    source_ids = fields["source_ids"]
    subtopic_num = fields.get("subtopic_number", "")
    subtopic_title = fields.get("subtopic_title", "Untitled")

    # ── Build source block (chapter name + source_guidance only) ──────────
    source_lines = []
    for src in source_ids:
        src_label = src.get("source_id", "Unknown")
        guidance = src.get("source_guidance") or src.get("key_claim") or "Use as evidence."
        source_lines.append(f"- {src_label}\n  {guidance}")
    sources_block = "\n\n".join(source_lines) if source_lines else "No sources specified."

    style_note_line = f"\n* {academic_style_notes}" if academic_style_notes else ""

    return f"""\
You are an academic writing assistant drafting a PhD dissertation section in English literature.
I have uploaded a Context Document (source_document) and several academic sources.

Your task is to write ONLY Subtopic {subtopic_num}: {subtopic_title}. Read the Context Document carefully to understand the chapter's overarching argument and how this specific subtopic fits into the Chapter Outline.
* Target length: ~{wc} words{style_note_line}

# SOURCES & DEPLOYMENT STRATEGY
You must use the following sources to build the argument. Follow the specific deployment guidance for each:
{sources_block}

# STRICT RULES
- Begin directly with the argument. No "In this section" openers.
- Continuous analytical paragraphs only. No bullet points, bolding, or subheadings within the section.
- Do not introduce outside arguments, sources, or scholars.
- Write as a scholar would: establish the claim, acknowledge what the existing approach achieves before critiquing it, name what the field loses by maintaining this pattern, and close by signalling what becomes possible once it is overcome."""


# ── Orchestration ──────────────────────────────────────────────────────────────

def _render_notebooklm_prompt(
    chapter: dict,
    subtopic: dict,
    previous_summary: Optional[dict],
    word_count_override: Optional[int],
    academic_style_notes: Optional[str],
) -> dict[str, str]:
    """
    Orchestrates Stage A + Stage B to produce all NotebookLM-facing text.

    `previous_summary` is accepted for backward compatibility with
    existing call-sites but is no longer auto-rendered into either
    output — the source document instead carries a placeholder, since
    previous-section summaries are pasted in manually and don't live in
    the chapterization JSON.

    Returns:
      source_document — upload as a NotebookLM source (context only)
      prompt_1        — paste into NotebookLM chat (instruction only)
    """
    source_doc_fields = _build_source_doc_fields(chapter, subtopic)
    prompt_fields = _build_prompt_fields(subtopic, word_count_override, academic_style_notes)

    return {
        "source_document": _render_source_document(source_doc_fields),
        "prompt_1": _render_prompt_1(prompt_fields),
    }


# ── Summary prompt renderer ───────────────────────────────────────────────────

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


# ── Chapter Source Map ────────────────────────────────────────────────────────

def get_chapter_source_map(chapter_id: str, thesis_id: str = "") -> list[dict]:
    """
    Returns a deduplicated list of source mappings for the entire chapter.
    Each mapping contains chapter_id, source_id, and file_name.
    """
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        return []

    # Aggregate all source_ids from all subtopics
    all_source_ids = []
    for subtopic in chapter.get("subtopics", []):
        for src in subtopic.get("source_ids", []):
            all_source_ids.append(src)

    if not all_source_ids:
        return []

    # Resolve to filenames and links
    resolved = _resolve_required_sources(all_source_ids, thesis_id=thesis_id)

    # Deduplicate based on exact match of chapter_id, source_id, and file_name
    seen = set()
    deduped = []
    for r in resolved:
        cid = r.get("chapter_id", "")
        sid = r.get("source_id", "")
        fname = r.get("file_name", "")
        key = (cid, sid, fname)
        if key not in seen:
            seen.add(key)
            deduped.append({
                "chapter_id": cid,
                "source_id": sid,
                "file_name": fname
            })

    return deduped
