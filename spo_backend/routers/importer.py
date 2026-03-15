"""
Import Router
-------------
JSON-based setup path. Replaces the slow field-by-field form flow for
initial project setup. Form-based endpoints in thesis.py and sources.py
remain fully functional for manual patches and corrections.

Endpoints:
  POST /import/thesis                  ← thesis.json
  POST /import/chapterization/{ch_id}  ← chapterization.json for one chapter
  POST /import/chapterization/bulk     ← multiple chapters in one upload
  POST /import/source                  ← source.json for one external work
  GET  /import/status                  ← what has been set up so far

JSON schemas are documented in /prompts/ — use those prompts with Claude
to generate the JSONs from your actual documents.
"""

from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from datetime import datetime
from services import storage
from services.source_importer import (
    _normalize_source_chapter,
    SourceChapterImport,
    SourceImport,
    do_auto_import,
)

router = APIRouter(prefix="/import", tags=["JSON Import"])


# ══════════════════════════════════════════════════════════════════════════════
# THESIS.JSON SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class ThesisImport(BaseModel):
    """
    Matches the preferred thesis.json schema exactly.
    The JSON uses core_argument (not central_argument) and
    nests theoretical_frameworks inside methodology.
    """
    # Identity
    document_type: Optional[str] = None
    title: str
    institution: Optional[str] = None
    researcher: Optional[str] = None
    author: Optional[str] = None
    year: Optional[int] = None
    degree: Optional[str] = None
    field: Optional[str] = None

    # Injected into prompts
    research_question: Optional[str] = None
    core_argument: str
    temporal_scope: Optional[str] = None
    research_gap: Optional[str] = None
    central_themes: list[str] = Field(default_factory=list)
    methodology: Optional[dict] = None

    # Reference only
    objectives: list[str] = Field(default_factory=list)
    key_authors_and_works: list[dict] = Field(default_factory=list)
    other_authors_mentioned: list[str] = Field(default_factory=list)
    theoretical_positions: Optional[dict] = None
    chapter_structure: list[dict] = Field(default_factory=list)
    expected_outcome: Optional[str] = None
    significance: Optional[dict] = None
    key_literature_review_findings: list[dict] = Field(default_factory=list)
    scope_and_limits: Optional[str] = None


@router.post("/thesis", summary="Import thesis.json")
def import_thesis(data: ThesisImport, thesis_id: str = Query("")):
    record = data.model_dump()
    record["updated_at"] = datetime.utcnow().isoformat()
    storage.write_synopsis(record, thesis_id=thesis_id)

    frameworks = []
    if data.methodology and isinstance(data.methodology, dict):
        frameworks = data.methodology.get("theoretical_frameworks", [])

    return {
        "imported": "thesis",
        "title": data.title,
        "author": data.researcher or data.author,
        "injected_into_prompts": [
            "core_argument", "temporal_scope", "research_gap",
            "central_themes", "methodology.theoretical_frameworks"
        ],
        "theoretical_frameworks_found": frameworks,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CHAPTERIZATION.JSON SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class SubtopicImport(BaseModel):
    number: str = Field(..., description="e.g. '1.3.2'")
    title: str
    goal: str = Field(..., description="What must this subtopic argue or establish?")
    position_in_argument: Optional[str] = Field(
        None,
        description="How does this subtopic serve the chapter arc?"
    )
    estimated_pages: Optional[int] = Field(
        None,
        description="Estimated page count for this subtopic."
    )
    source_ids: list[dict] = Field(
        default_factory=list,
        description=(
            "Sources assigned to this subtopic with per-source writing guidance. "
            "Each: {source_id, chapter_id, source_guidance}"
        )
    )


class ChapterizationImport(BaseModel):
    """
    Schema for chapterization.json — one chapter.
    Generate with /prompts/generate_chapterization_json.txt
    """
    number: int
    title: str
    goal: str = Field(
        ...,
        description="What must this chapter prove? How does it serve the thesis argument?"
    )
    chapter_arc: str = Field(
        ...,
        description=(
            "150–200 words. How all subtopics connect argumentatively within this chapter. "
            "Describes the argumentative movement and how subtopics build on each other."
        )
    )
    chapter_goal_statement: Optional[str] = Field(
        None,
        description=(
            "3–4 sentences on what the reader must understand by the end of this chapter. "
            "More precise than the goal field — states exactly what must be established."
        )
    )
    subtopics: list[SubtopicImport] = Field(
        ..., description="All subtopics in order.", min_length=1
    )
    sources_reserved_for_later_chapters: list[dict] = Field(
        default_factory=list,
        description=(
            "Sources explicitly excluded from this chapter. "
            "Each: {source_id, reserved_for, reason}"
        )
    )


def _build_chapter_record(chapter_id: str, data: ChapterizationImport) -> dict:
    """
    Single authority for turning a ChapterizationImport into a storage record.
    Called by both import_chapterization and import_chapterization_bulk so
    subtopic field list never diverges between the two endpoints.
    """
    now = datetime.utcnow().isoformat()
    subtopics = [
        {
            "subtopic_id": sub.number.replace(".", "_"),
            "number": sub.number,
            "title": sub.title,
            "goal": sub.goal,
            "position_in_argument": sub.position_in_argument,
            "estimated_pages": sub.estimated_pages,
            "source_ids": list(sub.source_ids),
        }
        for sub in data.subtopics
    ]
    return {
        "chapter_id": chapter_id,
        "number": data.number,
        "title": data.title,
        "goal": data.goal,
        "chapter_arc": data.chapter_arc,
        "chapter_goal_statement": data.chapter_goal_statement,
        "subtopics": subtopics,
        "sources_reserved_for_later_chapters": list(data.sources_reserved_for_later_chapters),
        "created_at": now,
        "updated_at": now,
    }


@router.post(
    "/chapterization/{chapter_id}",
    summary="Import chapterization.json — sets up chapter arc + all subtopics at once"
)
def import_chapterization(chapter_id: str, data: ChapterizationImport, thesis_id: str = Query("")):
    """
    Imports a full chapter: goal, arc, and all subtopics in one JSON.
    If the chapter already exists, it is overwritten.
    Subtopic IDs are auto-generated from the number (e.g. '1.3.2' → '1_3_2').
    """
    record = _build_chapter_record(chapter_id, data)
    storage.write_chapter(chapter_id, record, thesis_id=thesis_id)

    return {
        "imported": "chapter",
        "chapter_id": chapter_id,
        "title": data.title,
        "subtopics_created": len(record["subtopics"]),
        "chapter_arc_set": True,
        "arc_word_count": len(data.chapter_arc.split()),
        "source_ids_stored": sum(len(s.source_ids) for s in data.subtopics),
    }


@router.post(
    "/chapterization/bulk",
    summary="Bulk-import chapterization JSONs — multiple chapters in one upload"
)
def import_chapterization_bulk(chapters: list[ChapterizationImport], thesis_id: str = Query("")):
    """
    Accepts an array of chapter chapterization objects.
    Each chapter's `number` field is used as the chapter_id (e.g. 1 → 'ch1').
    """
    results = []
    for ch_data in chapters:
        chapter_id = f"ch{ch_data.number}"
        record = _build_chapter_record(chapter_id, ch_data)
        storage.write_chapter(chapter_id, record, thesis_id=thesis_id)
        results.append({
            "chapter_id": chapter_id,
            "title": ch_data.title,
            "subtopics_created": len(record["subtopics"]),
        })

    return {
        "imported": "chapterization_bulk",
        "chapters_created": len(results),
        "chapters": results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE.JSON IMPORT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/source", summary="Import source.json — creates group + all sources + index cards in one upload")
def import_source(data: dict = Body(...), thesis_id: str = Query("")):
    """
    Imports a complete external work:
      1 SourceGroup + N Sources + N IndexCards in one request.

    Delegates entirely to do_auto_import() in services/source_importer.py —
    the single authority for this logic, also used by drive.py's save_index_card.
    """
    result, error = do_auto_import(data, thesis_id=thesis_id)

    if error:
        raise HTTPException(status_code=422, detail=error)

    return {
        "imported": "source",
        "group_id": result["group_id"],
        "title": result["title"],
        "author": result["author"],
        "sources_created": result["sources_created"],
        "sources": result["sources"],
        "all_indexed": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/status", summary="Check what has been imported and what is still missing")
def import_status():
    synopsis = storage.read_synopsis()
    chapters = storage.list_chapters()
    groups = storage.list_source_groups()

    chapter_status = []
    for ch in chapters:
        ch_id = ch["chapter_id"]
        full = storage.read_chapter(ch_id)
        sub_count = len(full.get("subtopics", [])) if full else 0
        chapter_status.append({
            "chapter_id": ch_id,
            "title": ch.get("title"),
            "has_arc": bool(ch.get("chapter_arc")),
            "subtopic_count": sub_count,
        })

    source_status = []
    for g in groups:
        g_id = g["group_id"]
        sources = storage.list_sources(g_id)
        ready = sum(1 for s in sources if s.get("has_index_card"))
        source_status.append({
            "group_id": g_id,
            "title": g.get("title"),
            "author": g.get("author"),
            "total_sources": len(sources),
            "indexed_sources": ready,
        })

    warnings = []
    if not synopsis:
        warnings.append("No thesis synopsis. POST /import/thesis")
    for ch in chapter_status:
        if not ch["has_arc"]:
            warnings.append(f"Chapter '{ch['title']}' has no arc. Re-import with chapter_arc field.")
        if ch["subtopic_count"] == 0:
            warnings.append(f"Chapter '{ch['title']}' has no subtopics.")

    return {
        "synopsis": {
            "imported": bool(synopsis),
            "title": synopsis.get("title") if synopsis else None,
        },
        "chapters": chapter_status,
        "source_groups": source_status,
        "warnings": warnings,
        "ready_to_compile": len(warnings) == 0,
    }