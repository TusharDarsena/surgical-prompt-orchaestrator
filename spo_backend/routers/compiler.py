"""
Prompt Compiler Router
----------------------
Assembles Architect Mega-Prompt and NotebookLM prompt from stored data.

Architect prompt section order (updated):
  1. Thesis Context        (synopsis: central_argument, frameworks, temporal_scope)
  2. Chapter Arc           (NEW — the argumentative map of the whole chapter)
  3. Current Subtopic      (goal + position_in_argument)
  4. Previous Section      (consistency chain — what was just argued)
  5. Source Profiles       (index cards of relevant sources)
  6. Instructions          (three-step chain-of-thought)
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from services import storage

router = APIRouter(prefix="/compile", tags=["Prompt Compiler"])


class ArchitectPromptRequest(BaseModel):
    source_ids: list[dict] = []
    # Each: {"group_id": "abc", "source_id": "def"}


class NotebookLMRequest(BaseModel):
    word_count: Optional[int] = None
    academic_style_notes: Optional[str] = None


# ── Architect Prompt ───────────────────────────────────────────────────────────

@router.get(
    "/architect-prompt/{chapter_id}/{subtopic_id}",
    summary="Compile Architect Mega-Prompt (auto source detection)"
)
def compile_architect_prompt_auto(
    chapter_id: str,
    subtopic_id: str,
    include_previous_section: bool = Query(default=True),
):
    payload = _gather_payload(chapter_id, subtopic_id, source_refs=None)
    prompt = _render_prompt(payload, include_previous_section)
    return {
        "prompt": prompt,
        "meta": _build_meta(payload),
        "copy_instructions": (
            "Copy 'prompt' and paste into Claude. "
            "Claude outputs Task.md. Save it via POST /tasks/{chapter_id}/{subtopic_id}."
        )
    }


@router.post(
    "/architect-prompt/{chapter_id}/{subtopic_id}",
    summary="Compile Architect Mega-Prompt (manual source selection)"
)
def compile_architect_prompt_manual(
    chapter_id: str,
    subtopic_id: str,
    req: ArchitectPromptRequest,
    include_previous_section: bool = Query(default=True),
):
    payload = _gather_payload(chapter_id, subtopic_id, source_refs=req.source_ids)
    prompt = _render_prompt(payload, include_previous_section)
    return {
        "prompt": prompt,
        "meta": _build_meta(payload),
    }


# ── NotebookLM Prompt ──────────────────────────────────────────────────────────

@router.get(
    "/notebooklm-prompt/{chapter_id}/{subtopic_id}",
    summary="Compile NotebookLM prompt from approved Task.md"
)
def compile_notebooklm_prompt_get(
    chapter_id: str,
    subtopic_id: str,
    word_count: Optional[int] = Query(default=None),
    academic_style_notes: Optional[str] = Query(default=None),
):
    return _build_notebooklm_response(chapter_id, subtopic_id, word_count, academic_style_notes)


@router.post(
    "/notebooklm-prompt/{chapter_id}/{subtopic_id}",
    summary="Compile NotebookLM prompt (with style overrides)"
)
def compile_notebooklm_prompt_post(
    chapter_id: str,
    subtopic_id: str,
    req: NotebookLMRequest,
):
    return _build_notebooklm_response(
        chapter_id, subtopic_id, req.word_count, req.academic_style_notes
    )


# ── Data gathering ─────────────────────────────────────────────────────────────

def _gather_payload(chapter_id: str, subtopic_id: str, source_refs: Optional[list]) -> dict:
    # Synopsis — required
    synopsis = storage.read_synopsis()
    if not synopsis:
        raise HTTPException(
            status_code=422,
            detail="No thesis synopsis. POST /import/thesis first."
        )

    # Chapter — required
    chapter = storage.read_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    # Subtopic — required
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

    # Sources
    if source_refs:
        sources = []
        for ref in source_refs:
            s = storage.read_source(ref["group_id"], ref["source_id"])
            if not s:
                raise HTTPException(404, f"Source '{ref['source_id']}' not found.")
            if not s.get("has_index_card"):
                raise HTTPException(
                    422,
                    f"Source '{s.get('label')}' has no index card. Write one first."
                )
            sources.append(s)
    else:
        sources = storage.find_sources_for_subtopic(subtopic_id)

    if not sources:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No indexed sources tagged for subtopic '{subtopic_id}'. "
                "Tag sources via relevant_subtopics in their index cards, "
                "or use POST with explicit source_ids."
            )
        )

    # Previous section summary
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
        "chapter_arc": chapter.get("chapter_arc"),   # may be None for old chapters
        "subtopic": subtopic,
        "sources": sources,
        "previous_summary": previous_summary,
    }


# ── Architect prompt renderer ──────────────────────────────────────────────────

def _render_prompt(payload: dict, include_previous_section: bool) -> str:
    synopsis = payload["synopsis"]
    chapter = payload["chapter"]
    chapter_arc = payload.get("chapter_arc")
    subtopic = payload["subtopic"]
    sources = payload["sources"]
    previous_summary = payload["previous_summary"] if include_previous_section else None

    L = []  # lines

    # ── System Role ────────────────────────────────────────────────────────────
    L += [
        "SYSTEM ROLE",
        f"You are the Lead Academic Architect for a PhD-level thesis in "
        f"{synopsis.get('field', 'academic research')}. "
        "Your sole job is to generate a strict structural blueprint (Task.md) "
        "for a specific subtopic. You do not write prose. You build the scaffold.",
        "",
    ]

    # ── Section 1: Thesis Context ──────────────────────────────────────────────
    L += [
        "=" * 60,
        "SECTION 1: THESIS CONTEXT",
        "=" * 60,
        "",
        f"THESIS: {synopsis['title']}",
        f"AUTHOR: {synopsis['author']}",
        "",
        "CENTRAL ARGUMENT:",
        synopsis["central_argument"],
        "",
    ]

    if synopsis.get("theoretical_frameworks"):
        L += [
            "THEORETICAL FRAMEWORKS:",
            ", ".join(synopsis["theoretical_frameworks"]),
            "",
        ]

    if synopsis.get("temporal_scope"):
        L += [f"TEMPORAL SCOPE: {synopsis['temporal_scope']}", ""]

    if synopsis.get("scope_and_limits"):
        L += ["SCOPE AND LIMITS:", synopsis["scope_and_limits"], ""]

    # ── Section 2: Chapter Arc (NEW) ───────────────────────────────────────────
    L += [
        "=" * 60,
        "SECTION 2: CHAPTER ARC",
        "=" * 60,
        "",
        f"CHAPTER {chapter['number']}: {chapter['title']}",
        "",
        "CHAPTER GOAL:",
        chapter["goal"],
        "",
    ]

    if chapter_arc:
        L += [
            "CHAPTER ARGUMENTATIVE ARC:",
            "(This is the map of how all subtopics of this chapter connect. "
            "Every Task.md you generate must keep the current subtopic within "
            "its designated role in this arc. Do not let it drift.)",
            "",
            chapter_arc,
            "",
        ]
    else:
        L += [
            "CHAPTER ARC: Not set. Import chapterization.json to add one.",
            "(Without an arc, Task.md output may be less precisely scoped.)",
            "",
        ]

    # ── Section 3: Current Subtopic ────────────────────────────────────────────
    L += [
        "=" * 60,
        "SECTION 3: CURRENT SUBTOPIC",
        "=" * 60,
        "",
        f"SUBTOPIC: {subtopic['number']} — {subtopic['title']}",
        "",
        "GOAL:",
        subtopic["goal"],
        "",
    ]

    if subtopic.get("position_in_argument"):
        L += [
            "POSITION IN CHAPTER ARC:",
            subtopic["position_in_argument"],
            "",
        ]

    # ── Section 4: Previous Section ────────────────────────────────────────────
    if previous_summary:
        L += [
            "=" * 60,
            "SECTION 4: PREVIOUS SECTION CONTEXT",
            "(Do NOT repeat this. Build forward from it.)",
            "=" * 60,
            "",
            f"PREVIOUS: {previous_summary.get('subtopic_number', '')} — "
            f"{previous_summary.get('subtopic_title', '')}",
            "",
            "WHAT WAS ARGUED:",
            previous_summary["core_argument_made"],
            "",
        ]
        if previous_summary.get("key_terms_established"):
            L += [
                "TERMS ESTABLISHED (use consistently, do not redefine):",
                ", ".join(previous_summary["key_terms_established"]),
                "",
            ]
        if previous_summary.get("what_next_section_must_build_on"):
            L += [
                "THIS SECTION MUST BUILD ON:",
                previous_summary["what_next_section_must_build_on"],
                "",
            ]
    else:
        L += [
            "=" * 60,
            "SECTION 4: PREVIOUS SECTION CONTEXT",
            "N/A — First subtopic of this chapter.",
            "=" * 60,
            "",
        ]

    # ── Section 5: Source Profiles ─────────────────────────────────────────────
    L += [
        "=" * 60,
        "SECTION 5: SOURCE PROFILES",
        "(Draw arguments ONLY from these sources. No outside knowledge.)",
        "=" * 60,
        "",
    ]

    for src in sources:
        label = src.get("label", "Source")
        card = src.get("index_card", {})
        L.append(f"── {label} ──────────────────────")

        group_id = src.get("group_id")
        if group_id:
            grp = storage.read_source_group(group_id)
            if grp:
                L.append(
                    f"From: {grp.get('author', '')} ({grp.get('year', '')}) "
                    f"— {grp.get('title', '')}"
                )

        if src.get("chapter_or_section"):
            L.append(f"Section: {src['chapter_or_section']}")
        if src.get("page_range"):
            L.append(f"Pages: {src['page_range']}")
        if card.get("time_period_covered"):
            L.append(f"Period: {card['time_period_covered']}")
        L.append("")

        L.append("KEY CLAIMS:")
        for claim in card.get("key_claims", []):
            L.append(f"  • {claim}")
        L.append("")

        L.append(f"THEMES: {', '.join(card.get('themes', []))}")
        L.append("")

        if card.get("limitations"):
            L += ["LIMITATIONS:", f"  {card['limitations']}", ""]

        if card.get("notable_authors_cited"):
            L += [f"Scholars cited: {', '.join(card['notable_authors_cited'])}", ""]

        L.append("")

    # ── Section 6: Instructions ────────────────────────────────────────────────
    L += [
        "=" * 60,
        "SECTION 6: INSTRUCTIONS",
        "=" * 60,
        "",
        "Process in exactly three steps. Show your work at each step.",
        "",
        "STEP 1 — CONTEXT ALIGNMENT",
        "  a) What argument must this subtopic make to fulfil its role in the Chapter Arc?",
        "  b) Which specific claims from the Source Profiles directly support this?",
        "  c) Does anything required by the subtopic goal lack source support?",
        "     If yes — flag it explicitly. Do not invent evidence.",
        "",
        "STEP 2 — THE DRAFT",
        "  Draft 3–5 focus points.",
        "  Rules:",
        "  • Every point must cite its source label (e.g. '[Sharma Ch.2]')",
        "  • If previous section established key terms, use them — do not redefine",
        "  • No point may rely on knowledge outside the provided Source Profiles",
        "  • Stay within the argumentative role assigned in the Chapter Arc",
        "",
        "STEP 3 — THE CRITIC",
        "  • Does each point sound like a specific academic argument or generic filler?",
        "  • Cut any bullet that could appear in ANY thesis on this topic",
        "  • Does the scope stay within the Chapter Arc role for this subtopic?",
        "",
        "FINAL OUTPUT — Task.md in a markdown code block:",
        "",
        "  ## Core Objective",
        "  One sentence. What this section establishes.",
        "",
        "  ## Focus Points",
        "  3–5 bullets. Each names its source.",
        "  Format: '- [Argument]. [Source label]'",
        "",
        "  ## Key Terms to Use",
        "  Terms from previous sections + new terms this section introduces.",
        "",
        "  ## Do Not Include",
        "  Tangents, over-broad claims, source limitations to avoid.",
        "",
    ]

    return "\n".join(L)


# ── NotebookLM prompt ──────────────────────────────────────────────────────────

def _build_notebooklm_response(
    chapter_id: str,
    subtopic_id: str,
    word_count: Optional[int],
    academic_style_notes: Optional[str],
) -> dict:
    blueprint = storage.read_task_blueprint(chapter_id, subtopic_id)
    if not blueprint:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No approved Task.md for '{subtopic_id}'. "
                "Complete the Architect phase first."
            )
        )

    chapter = storage.read_chapter(chapter_id)
    previous_summary = None
    if chapter:
        subtopics = chapter.get("subtopics", [])
        ids = [s["subtopic_id"] for s in subtopics]
        if subtopic_id in ids:
            idx = ids.index(subtopic_id)
            if idx > 0:
                previous_summary = storage.read_section_summary(chapter_id, ids[idx - 1])

    tagged = storage.find_sources_for_subtopic(subtopic_id)
    file_list = [
        s.get("file_name") or s.get("label", "unnamed")
        for s in tagged if s.get("has_index_card")
    ]

    prompt = _render_notebooklm_prompt(
        blueprint, previous_summary, word_count, academic_style_notes
    )

    return {
        "prompt": prompt,
        "meta": {
            "subtopic": f"{blueprint.get('subtopic_number')} — {blueprint.get('subtopic_title')}",
            "task_md_approved": blueprint.get("approved", False),
            "previous_section_included": previous_summary is not None,
            "previous_section": (
                f"{previous_summary.get('subtopic_number')} — {previous_summary.get('subtopic_title')}"
                if previous_summary else None
            ),
            "suggested_pdf_uploads": file_list,
        },
        "next_step": (
            f"1. Upload PDFs to NotebookLM. "
            f"2. Paste the prompt. "
            f"3. After approving draft: POST /consistency/{chapter_id}/{subtopic_id}"
        )
    }


def _render_notebooklm_prompt(
    blueprint: dict,
    previous_summary: Optional[dict],
    word_count: Optional[int],
    academic_style_notes: Optional[str],
) -> str:
    L = []
    subtopic_ref = f"{blueprint.get('subtopic_number', '')} — {blueprint.get('subtopic_title', '')}"

    L += [
        f"Write section {subtopic_ref} of the thesis.",
        "",
        "Follow the blueprint below STRICTLY.",
        "Use ONLY the uploaded PDF sources. Do not draw on outside knowledge.",
        "Do not invent citations, statistics, or historical claims.",
        "",
    ]

    wc = word_count or blueprint.get("word_count_target")
    if wc:
        L += [f"TARGET LENGTH: approximately {wc} words.", ""]

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

    L += ["=" * 50, "WRITING BLUEPRINT (Task.md)", "=" * 50, ""]

    if blueprint.get("core_objective"):
        L += [f"CORE OBJECTIVE: {blueprint['core_objective']}", ""]

    if blueprint.get("focus_points"):
        L += ["FOCUS POINTS (cover all, in this order):"]
        for p in blueprint["focus_points"]:
            L.append(f"  • {p}")
        L.append("")
    elif blueprint.get("raw_markdown"):
        L += [blueprint["raw_markdown"], ""]

    if blueprint.get("key_terms"):
        L += [f"KEY TERMS: {', '.join(blueprint['key_terms'])}", ""]

    if blueprint.get("do_not_include"):
        L += ["DO NOT INCLUDE:"]
        for item in blueprint["do_not_include"]:
            L.append(f"  ✗ {item}")
        L.append("")

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


# ── Meta helpers ───────────────────────────────────────────────────────────────

def _build_meta(payload: dict) -> dict:
    sources_summary = [
        {"label": s.get("label"), "title": s.get("title")}
        for s in payload["sources"]
    ]
    prev = payload.get("previous_summary")
    return {
        "synopsis_loaded": True,
        "chapter": f"{payload['chapter']['number']} — {payload['chapter']['title']}",
        "chapter_arc_set": bool(payload.get("chapter_arc")),
        "subtopic": f"{payload['subtopic']['number']} — {payload['subtopic']['title']}",
        "sources_included": sources_summary,
        "source_count": len(sources_summary),
        "previous_section_included": prev is not None,
        "previous_section": (
            f"{prev.get('subtopic_number')} — {prev.get('subtopic_title')}" if prev else None
        ),
        "warnings": _collect_warnings(payload),
    }


def _collect_warnings(payload: dict) -> list[str]:
    warnings = []
    if not payload.get("chapter_arc"):
        warnings.append(
            "No chapter arc set. Import chapterization.json to add one. "
            "Task.md output will be less precisely scoped without it."
        )
    if len(payload["sources"]) > 5:
        warnings.append(
            f"{len(payload['sources'])} sources included. Consider narrowing to 3–4."
        )
    for s in payload["sources"]:
        card = s.get("index_card", {})
        if not card.get("limitations"):
            warnings.append(
                f"Source '{s.get('label')}' has no limitations field. "
                "Adding one improves the 'Do Not Include' section of Task.md."
            )
    if payload.get("previous_summary") is None:
        subtopics = payload["chapter"].get("subtopics", [])
        if subtopics and subtopics[0]["subtopic_id"] != payload["subtopic"]["subtopic_id"]:
            warnings.append(
                "No previous section summary found. "
                "If not the first subtopic, save one via POST /consistency/..."
            )
    return warnings