# ── REPLACE the existing _build_notebooklm_response() and _render_notebooklm_prompt()
# ── in compiler.py with these versions.
# ── Also replace the two route handlers (compile_notebooklm_prompt_get and _post)
# ── with the single new GET handler below.
# ── The NotebookLMRequest model and old _build_notebooklm_response can be deleted.


# ── New route handler ──────────────────────────────────────────────────────────

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
    Builds the NotebookLM prompt directly from chapterization data.
    No Task.md required. source_guidance fields from chapterization become
    the Focus Points injected into the prompt.

    Also returns meta.required_sources — the list of files needed for this
    subtopic, resolved against the local folder scan if available.
    """
    return _build_notebooklm_response(chapter_id, subtopic_id, word_count, academic_style_notes)


# ── Data builder ───────────────────────────────────────────────────────────────

def _build_notebooklm_response(
    chapter_id: str,
    subtopic_id: str,
    word_count: Optional[int],
    academic_style_notes: Optional[str],
) -> dict:

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

    # source_ids from chapterization — these drive the prompt, not the DB sources
    source_ids = subtopic.get("source_ids", [])

    # Previous section summary — same chain logic as before
    previous_summary = None
    ids_in_order = [s["subtopic_id"] for s in subtopics]
    if subtopic_id in ids_in_order:
        idx = ids_in_order.index(subtopic_id)
        if idx > 0:
            prev_id = ids_in_order[idx - 1]
            previous_summary = storage.read_section_summary(chapter_id, prev_id)

    # Word count from estimated_pages if not explicitly provided
    effective_wc = word_count
    if not effective_wc and subtopic.get("estimated_pages"):
        effective_wc = subtopic["estimated_pages"] * 250

    # Build required_sources — resolve each source_id + chapter_id to a filename/link
    required_sources = _resolve_required_sources(source_ids)

    # Build prompt
    prompt = _render_notebooklm_prompt(
        chapter=chapter,
        subtopic=subtopic,
        source_ids=source_ids,
        previous_summary=previous_summary,
        word_count=effective_wc,
        academic_style_notes=academic_style_notes,
    )

    # Warnings
    warnings = []
    if not source_ids:
        warnings.append(
            f"Subtopic '{subtopic_id}' has no source_ids in chapterization data. "
            "Re-import chapterization JSON with source_ids populated."
        )
    if not previous_summary and ids_in_order.index(subtopic_id) > 0:
        warnings.append("No previous section summary found. Save one after writing the previous subtopic.")
    unresolved = [r for r in required_sources if r["file_name"] is None]
    if unresolved:
        warnings.append(
            f"{len(unresolved)} source(s) could not be matched to a local file. "
            "Run Scan Folder on the Source Library page or check thesis folder names."
        )

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
            "source_count": len(source_ids),
            "required_sources": required_sources,
            "word_count_target": effective_wc,
            "warnings": warnings,
        },
        "next_step": (
            "1. Check required_sources — upload those PDFs to NotebookLM. "
            "2. Paste the prompt. "
            "3. Save the draft via POST /sections/{chapter_id}/{subtopic_id}/draft. "
            "4. Save consistency summary via POST /consistency/{chapter_id}/{subtopic_id}."
        )
    }


def _resolve_required_sources(source_ids: list[dict]) -> list[dict]:
    """
    For each entry in source_ids, resolve the thesis name + chapter_id
    to a local filename (and Drive link if available) using the scan dictionary.

    Returns a list of dicts:
        {
            "source_id": "A study of feminine angst... (Puhan, 2018)",
            "chapter_id": "Introduction",
            "source_guidance": "Use Puhan's claim...",
            "file_name": "07_chapter 1.pdf",   # None if unresolved
            "drive_link": None,                 # populated when Drive links registered
        }
    """
    results = []
    for entry in source_ids:
        thesis_name = entry.get("source_id", "")
        chapter_id_raw = entry.get("chapter_id", "")
        source_guidance = entry.get("source_guidance", "")

        # resolve_source_files handles AND-splitting and fuzzy chapter matching
        resolved = storage.resolve_source_files(thesis_name, chapter_id_raw)

        if not resolved:
            # Scan not run or thesis not found — return unresolved entry
            results.append({
                "source_id": thesis_name,
                "chapter_id": chapter_id_raw,
                "source_guidance": source_guidance,
                "file_name": None,
                "drive_link": None,
            })
        else:
            # May return multiple files if chapter_id had AND
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
    source_ids: list[dict],
    previous_summary: Optional[dict],
    word_count: Optional[int],
    academic_style_notes: Optional[str],
) -> str:
    L = []

    subtopic_ref = f"{subtopic.get('number', '')} — {subtopic.get('title', '')}"

    L += [
        f"Write section {subtopic_ref} of the thesis.",
        "",
        "Follow the blueprint below STRICTLY.",
        "Use ONLY the uploaded PDF sources. Do not draw on outside knowledge.",
        "Do not invent citations, statistics, or historical claims.",
        "",
    ]

    if word_count:
        L += [f"TARGET LENGTH: approximately {word_count} words.", ""]

    # ── Previous section context ───────────────────────────────────────────────
    if previous_summary:
        L += [
            "=" * 50,
            "PREVIOUS SECTION CONTEXT — Do NOT repeat. Build forward.",
            "=" * 50,
            "",
            f"Previous section ({previous_summary.get('subtopic_number', '')}) established:",
            previous_summary.get("core_argument_made", ""),
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

    # ── Chapter arc context ────────────────────────────────────────────────────
    if chapter.get("chapter_arc"):
        L += [
            "=" * 50,
            "CHAPTER ARC — Your section's role in the chapter argument.",
            "=" * 50,
            "",
            chapter["chapter_arc"],
            "",
        ]

    # ── Core objective from subtopic goal ─────────────────────────────────────
    L += [
        "=" * 50,
        "WRITING BLUEPRINT",
        "=" * 50,
        "",
        "CORE OBJECTIVE:",
        subtopic.get("goal", ""),
        "",
    ]

    if subtopic.get("position_in_argument"):
        L += [
            "SCOPE CONTROL — Stay within this role:",
            subtopic["position_in_argument"],
            "",
        ]

    # ── Focus points from source_guidance ─────────────────────────────────────
    # Each source entry's source_guidance becomes one named focus point.
    # This is the key improvement over the old Task.md approach —
    # the guidance is surgical and already written, not generated by Architect.
    if source_ids:
        L += ["FOCUS POINTS — Cover all, in this order:"]
        for i, entry in enumerate(source_ids, 1):
            thesis_name = entry.get("source_id", "Source")
            chapter_ref = entry.get("chapter_id", "")
            guidance = entry.get("source_guidance", "")
            # Short label: use last parenthetical if present (e.g. "Puhan, 2018")
            # otherwise truncate thesis name
            import re
            paren_match = re.search(r'\(([^)]+)\)$', thesis_name)
            short_label = paren_match.group(1) if paren_match else thesis_name[:30]
            if chapter_ref:
                short_label += f" · {chapter_ref}"
            L.append(f"  {i}. [{short_label}]")
            if guidance:
                # Wrap guidance lines for readability
                L.append(f"     {guidance}")
            L.append("")

    # ── Do Not Include from sources_reserved_for_later_chapters ───────────────
    reserved = chapter.get("sources_reserved_for_later_chapters", [])
    if reserved:
        L += ["DO NOT INCLUDE (reserved for later chapters):"]
        for r in reserved:
            src = r.get("source_id", "")
            reason = r.get("reason", "")
            L.append(f"  ✗ {src}")
            if reason:
                L.append(f"    ({reason})")
        L.append("")

    # ── Writing rules ──────────────────────────────────────────────────────────
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
        "• Stay within the argumentative role assigned in the Chapter Arc.",
    ]

    if academic_style_notes:
        L += ["", f"STYLE NOTES: {academic_style_notes}"]

    return "\n".join(L)
