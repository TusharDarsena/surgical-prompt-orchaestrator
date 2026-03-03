"""
Prompt Compiler Router
----------------------
Assembles the Architect Mega-Prompt from stored thesis context,
source index cards, and consistency chain data.

The output is a single string you copy and paste into Claude.
Claude reads it and outputs a Task.md blueprint.

Two endpoints:

  GET  /compile/architect-prompt/{chapter_id}/{subtopic_id}
       Full prompt using auto-detected sources (tagged for this subtopic)

  POST /compile/architect-prompt/{chapter_id}/{subtopic_id}
       Same, but you specify EXACTLY which source IDs to include.
       Use this when auto-detection misses something or includes too much.

Query params (both endpoints):
  include_previous_section: bool (default True)
    Whether to include the previous section's consistency summary.
    Set to False for the very first subtopic of a chapter.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from services import storage

router = APIRouter(prefix="/compile", tags=["Prompt Compiler"])


# ── Request model for manual source selection ─────────────────────────────────

class ArchitectPromptRequest(BaseModel):
    source_ids: list[dict] = []
    # Each entry: {"group_id": "abc123", "source_id": "def456"}
    # If empty, falls back to auto-detection via relevant_subtopics tags


# ── Main endpoints ─────────────────────────────────────────────────────────────

@router.get(
    "/architect-prompt/{chapter_id}/{subtopic_id}",
    response_model=dict,
    summary="Compile Architect Mega-Prompt (auto source detection)"
)
def compile_architect_prompt_auto(
    chapter_id: str,
    subtopic_id: str,
    include_previous_section: bool = Query(
        default=True,
        description="Include previous section summary for consistency. False for first subtopic."
    )
):
    """
    Assembles the full Architect Mega-Prompt using sources auto-detected
    from index card tagging (relevant_subtopics field).

    Returns both the compiled prompt text AND a metadata block showing
    exactly what was included, so you can verify before copying.
    """
    payload = _gather_payload(chapter_id, subtopic_id, source_refs=None)
    prompt = _render_prompt(payload, include_previous_section)

    return {
        "prompt": prompt,
        "meta": _build_meta(payload),
        "copy_instructions": (
            "Copy the value of 'prompt' and paste it directly into Claude. "
            "Claude will output a Task.md blueprint. "
            "Paste that Task.md back into your app for review before using with NotebookLM."
        )
    }


@router.post(
    "/architect-prompt/{chapter_id}/{subtopic_id}",
    response_model=dict,
    summary="Compile Architect Mega-Prompt (manual source selection)"
)
def compile_architect_prompt_manual(
    chapter_id: str,
    subtopic_id: str,
    req: ArchitectPromptRequest,
    include_previous_section: bool = Query(default=True)
):
    """
    Same as GET but you specify exactly which sources to include.
    Use when auto-detection gives wrong results.

    Body example:
    {
      "source_ids": [
        {"group_id": "abc123", "source_id": "def456"},
        {"group_id": "abc123", "source_id": "ghi789"}
      ]
    }
    """
    payload = _gather_payload(chapter_id, subtopic_id, source_refs=req.source_ids)
    prompt = _render_prompt(payload, include_previous_section)

    return {
        "prompt": prompt,
        "meta": _build_meta(payload),
        "copy_instructions": (
            "Copy the value of 'prompt' and paste it directly into Claude."
        )
    }


# ── Data gathering ─────────────────────────────────────────────────────────────

def _gather_payload(chapter_id: str, subtopic_id: str, source_refs: Optional[list]) -> dict:
    """
    Pulls all data needed for the prompt from storage.
    Raises informative errors if anything required is missing.
    """

    # 1. Synopsis — required
    synopsis = storage.read_synopsis()
    if not synopsis:
        raise HTTPException(
            status_code=422,
            detail=(
                "No thesis synopsis found. "
                "POST /thesis/synopsis before compiling a prompt."
            )
        )

    # 2. Chapter — required
    chapter = storage.read_chapter(chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=404,
            detail=f"Chapter '{chapter_id}' not found."
        )

    # 3. Subtopic — required
    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Subtopic '{subtopic_id}' not found in chapter '{chapter_id}'. "
                f"Available: {[s['subtopic_id'] for s in subtopics]}"
            )
        )

    # 4. Sources with index cards
    if source_refs:
        # Manual selection
        sources = []
        for ref in source_refs:
            s = storage.read_source(ref["group_id"], ref["source_id"])
            if not s:
                raise HTTPException(
                    status_code=404,
                    detail=f"Source '{ref['source_id']}' in group '{ref['group_id']}' not found."
                )
            if not s.get("has_index_card"):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Source '{s.get('label', ref['source_id'])}' has no index card. "
                        "Write an index card before including it in a prompt."
                    )
                )
            sources.append(s)
    else:
        # Auto-detect from relevant_subtopics tags
        sources = storage.find_sources_for_subtopic(subtopic_id)

    if not sources:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No sources with index cards are tagged for subtopic '{subtopic_id}'. "
                "Either: (1) add relevant_subtopics tags to your index cards, "
                "or (2) use POST with explicit source_ids."
            )
        )

    # 5. Previous section summary (optional — no error if missing)
    previous_summary = None
    ids_in_order = [s["subtopic_id"] for s in subtopics]
    if subtopic_id in ids_in_order:
        idx = ids_in_order.index(subtopic_id)
        if idx > 0:
            prev_id = ids_in_order[idx - 1]
            previous_summary = storage.read_section_summary(chapter_id, prev_id)

    return {
        "synopsis": synopsis,
        "chapter": chapter,
        "subtopic": subtopic,
        "sources": sources,
        "previous_summary": previous_summary,
    }


# ── Prompt renderer ────────────────────────────────────────────────────────────

def _render_prompt(payload: dict, include_previous_section: bool) -> str:
    """
    Renders the Architect Mega-Prompt as a single string.

    Structure:
      SYSTEM ROLE
      === THESIS CONTEXT ===
        Synopsis
        Chapter Goal
        Current Subtopic
      === PREVIOUS SECTION === (if available and requested)
      === SOURCE PROFILES ===
        One block per source index card
      === INSTRUCTIONS ===
        Three-step chain-of-thought process
    """
    synopsis = payload["synopsis"]
    chapter = payload["chapter"]
    subtopic = payload["subtopic"]
    sources = payload["sources"]
    previous_summary = payload["previous_summary"] if include_previous_section else None

    lines = []

    # ── System Role ────────────────────────────────────────────────────────────
    lines += [
        "SYSTEM ROLE",
        "You are the Lead Academic Architect for a PhD-level thesis in "
        f"{synopsis.get('field', 'academic research')}. "
        "Your sole job is to generate a strict structural blueprint (Task.md) "
        "for a specific subtopic. You do not write prose. You build the scaffold "
        "that will guide the writing.",
        "",
    ]

    # ── Thesis Context ─────────────────────────────────────────────────────────
    lines += [
        "=" * 60,
        "SECTION 1: THESIS CONTEXT",
        "=" * 60,
        "",
        f"THESIS TITLE: {synopsis['title']}",
        f"AUTHOR: {synopsis['author']}",
        "",
        "CENTRAL ARGUMENT OF THE THESIS:",
        synopsis["central_argument"],
        "",
    ]

    if synopsis.get("theoretical_framework"):
        lines += [
            "THEORETICAL FRAMEWORK:",
            synopsis["theoretical_framework"],
            "",
        ]

    if synopsis.get("scope_and_limits"):
        lines += [
            "SCOPE AND LIMITS:",
            synopsis["scope_and_limits"],
            "",
        ]

    lines += [
        "-" * 40,
        f"CHAPTER {chapter['number']}: {chapter['title']}",
        "",
        "CHAPTER GOAL:",
        chapter["goal"],
        "",
        "-" * 40,
        f"CURRENT SUBTOPIC: {subtopic['number']} — {subtopic['title']}",
        "",
        "SUBTOPIC GOAL:",
        subtopic["goal"],
        "",
    ]

    if subtopic.get("position_in_argument"):
        lines += [
            "POSITION IN CHAPTER ARGUMENT:",
            subtopic["position_in_argument"],
            "",
        ]

    # ── Previous Section ───────────────────────────────────────────────────────
    if previous_summary:
        lines += [
            "=" * 60,
            "SECTION 2: PREVIOUS SECTION CONTEXT",
            "(The section written just before this one. Use this to maintain",
            "argumentative continuity — do NOT repeat what was already established.)",
            "=" * 60,
            "",
            f"PREVIOUS SUBTOPIC: {previous_summary.get('subtopic_number', '')} — "
            f"{previous_summary.get('subtopic_title', '')}",
            "",
            "WHAT WAS ARGUED:",
            previous_summary["core_argument_made"],
            "",
        ]

        if previous_summary.get("key_terms_established"):
            terms = ", ".join(previous_summary["key_terms_established"])
            lines += [
                "KEY TERMS ALREADY ESTABLISHED (use these consistently, do not redefine):",
                terms,
                "",
            ]

        if previous_summary.get("what_next_section_must_build_on"):
            lines += [
                "THIS SECTION MUST BUILD ON:",
                previous_summary["what_next_section_must_build_on"],
                "",
            ]
    else:
        lines += [
            "=" * 60,
            "SECTION 2: PREVIOUS SECTION CONTEXT",
            "N/A — This is the first subtopic of this chapter.",
            "=" * 60,
            "",
        ]

    # ── Source Profiles ────────────────────────────────────────────────────────
    lines += [
        "=" * 60,
        "SECTION 3: AVAILABLE SOURCE PROFILES",
        "(These are the ONLY sources you may draw arguments from.",
        "Do not reference any source not listed here.)",
        "=" * 60,
        "",
    ]

    for i, source in enumerate(sources):
        label = source.get("label", f"Source {chr(65 + i)}")
        card = source.get("index_card", {})

        lines += [f"── {label} ──────────────────────────────────"]

        # Parent group context if available
        group_id = source.get("group_id")
        if group_id:
            group = storage.read_source_group(group_id)
            if group:
                lines.append(
                    f"From: {group.get('author', '')} ({group.get('year', '')}) "
                    f"— {group.get('title', '')}"
                )

        if source.get("chapter_or_section"):
            lines.append(f"Section: {source['chapter_or_section']}")
        if source.get("page_range"):
            lines.append(f"Pages: {source['page_range']}")

        lines.append("")

        if card.get("time_period_covered"):
            lines += [f"Time period covered: {card['time_period_covered']}", ""]

        lines.append("KEY CLAIMS THIS SOURCE MAKES:")
        for claim in card.get("key_claims", []):
            lines.append(f"  • {claim}")
        lines.append("")

        lines.append(f"THEMES: {', '.join(card.get('themes', []))}")
        lines.append("")

        if card.get("limitations"):
            lines += [
                "LIMITATIONS (arguments this source CANNOT support):",
                f"  {card['limitations']}",
                "",
            ]

        if card.get("notable_authors_cited"):
            lines += [
                f"Notable scholars cited: {', '.join(card['notable_authors_cited'])}",
                "",
            ]

        lines.append("")

    # ── Instructions ───────────────────────────────────────────────────────────
    lines += [
        "=" * 60,
        "SECTION 4: YOUR INSTRUCTIONS",
        "=" * 60,
        "",
        "Process this request in exactly three steps. Do not skip or merge steps.",
        "Show your work for each step.",
        "",
        "STEP 1 — CONTEXT ALIGNMENT (The Thinker)",
        "Read the thesis synopsis and the subtopic goal carefully.",
        "Answer these questions:",
        "  a) What core argument must this subtopic make to serve the chapter goal?",
        "  b) Which specific claims from the Source Profiles above directly support this?",
        "  c) Is there anything the subtopic goal requires that NO source profile covers?",
        "     (If yes, flag it explicitly — do not invent evidence.)",
        "",
        "STEP 2 — THE DRAFT",
        "Draft a bulleted scope for this subtopic.",
        "Rules:",
        "  • Every bullet must cite which Source label supports it (e.g. '[Sharma Ch.2]')",
        "  • If the previous section established key terms, use them — do not redefine",
        "  • No bullet may rely on knowledge outside the provided Source Profiles",
        "  • 3 to 5 focus points only — quality over quantity",
        "",
        "STEP 3 — THE CRITIC",
        "Review your draft against these questions:",
        "  • Does each point sound like a specific academic argument or generic filler?",
        "  • Cut any bullet that could appear in ANY thesis on this topic",
        "  • Does the scope connect logically to the previous section context?",
        "  • Is the argumentative direction clear?",
        "",
        "FINAL OUTPUT",
        "Output the approved blueprint as a markdown code block titled Task.md.",
        "It must contain exactly these four sections:",
        "",
        "  ## Core Objective",
        "  One sentence. What this section establishes or proves.",
        "",
        "  ## Focus Points",
        "  3–5 bullets. Each must name the source it draws from.",
        "  Format: '- [Argument]. [Source label, e.g. Sharma Ch.2]'",
        "",
        "  ## Key Terms to Use",
        "  Terms established in previous sections that must appear consistently.",
        "  Add any new terms this section introduces.",
        "",
        "  ## Do Not Include",
        "  Explicit list of tangents, over-broad claims, or source limitations",
        "  that would weaken this section. Be specific.",
        "",
    ]

    return "\n".join(lines)


# ── Metadata summary ───────────────────────────────────────────────────────────

def _build_meta(payload: dict) -> dict:
    """
    Returns a human-readable summary of what was included in the prompt.
    Use this to verify the compiler picked up the right data.
    """
    sources_summary = [
        {
            "label": s.get("label"),
            "title": s.get("title"),
            "has_index_card": s.get("has_index_card"),
            "group_id": s.get("group_id"),
        }
        for s in payload["sources"]
    ]

    prev = payload.get("previous_summary")

    return {
        "synopsis_loaded": True,
        "chapter": f"{payload['chapter']['number']} — {payload['chapter']['title']}",
        "subtopic": f"{payload['subtopic']['number']} — {payload['subtopic']['title']}",
        "sources_included": sources_summary,
        "source_count": len(sources_summary),
        "previous_section_included": prev is not None,
        "previous_section": (
            f"{prev.get('subtopic_number')} — {prev.get('subtopic_title')}"
            if prev else None
        ),
        "warnings": _collect_warnings(payload),
    }


def _collect_warnings(payload: dict) -> list[str]:
    warnings = []

    if len(payload["sources"]) == 0:
        warnings.append("No sources included. Prompt will be weak.")

    if len(payload["sources"]) > 5:
        warnings.append(
            f"{len(payload['sources'])} sources included. "
            "Consider narrowing to 3-4 most relevant for a tighter Task.md."
        )

    for s in payload["sources"]:
        card = s.get("index_card", {})
        if not card.get("limitations"):
            warnings.append(
                f"Source '{s.get('label')}' has no limitations field. "
                "Adding one improves the Task.md 'Do Not Include' section."
            )

    if payload.get("previous_summary") is None:
        subtopics = payload["chapter"].get("subtopics", [])
        if subtopics and subtopics[0]["subtopic_id"] != payload["subtopic"]["subtopic_id"]:
            warnings.append(
                "No previous section summary found. "
                "If this is not the first subtopic, save a summary after completing "
                "the previous section via POST /consistency/{chapter_id}/{subtopic_id}."
            )

    return warnings