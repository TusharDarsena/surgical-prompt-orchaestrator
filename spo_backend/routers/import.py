"""
Import Router
-------------
JSON-based setup path. Replaces the slow field-by-field form flow for
initial project setup. Form-based endpoints in thesis.py and sources.py
remain fully functional for manual patches and corrections.

Endpoints:
  POST /import/thesis                  ← thesis.json
  POST /import/chapterization/{ch_id}  ← chapterization.json for one chapter
  POST /import/source                  ← source.json for one external work
  GET  /import/status                  ← what has been set up so far

JSON schemas are documented in /prompts/ — use those prompts with Claude
to generate the JSONs from your actual documents.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from services import storage

router = APIRouter(prefix="/import", tags=["JSON Import"])


# ══════════════════════════════════════════════════════════════════════════════
# THESIS.JSON SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class ThesisImport(BaseModel):
    """
    Schema for thesis.json.
    Generate this by giving Claude your synopsis document with the prompt
    in /prompts/generate_thesis_json.txt
    """
    title: str
    author: str
    field: str

    # ── Injected into Architect prompts ────────────────────────────────────────
    central_argument: str = Field(
        ...,
        description="2–4 sentences. The single claim the thesis argues and proves."
    )
    theoretical_frameworks: list[str] = Field(
        ...,
        description="e.g. ['Postcolonial feminism', 'New Historicism']"
    )
    temporal_scope: Optional[str] = Field(
        None,
        description="Time period covered. e.g. '1947–1990'"
    )

    # ── Reference only ─────────────────────────────────────────────────────────
    research_questions: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    methodology: Optional[str] = None
    key_authors: list[str] = Field(default_factory=list)
    central_themes: list[str] = Field(default_factory=list)
    chapter_structure_overview: Optional[str] = None
    scope_and_limits: Optional[str] = None


@router.post("/thesis", summary="Import thesis.json — replaces synopsis form")
def import_thesis(data: ThesisImport):
    """
    Upload your thesis.json to set up the thesis synopsis.
    Overwrites any existing synopsis.
    """
    record = data.model_dump()
    record["updated_at"] = datetime.utcnow().isoformat()
    storage.write_synopsis(record)
    return {
        "imported": "thesis",
        "title": data.title,
        "injected_fields": ["central_argument", "theoretical_frameworks", "temporal_scope"],
        "reference_only_fields": [
            "research_questions", "objectives", "methodology",
            "key_authors", "central_themes", "chapter_structure_overview", "scope_and_limits"
        ]
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


class ChapterizationImport(BaseModel):
    """
    Schema for chapterization.json — one file per chapter.
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
            "Describe the argumentative movement: what each subtopic establishes, "
            "how they build on each other, and what the chapter achieves by the end. "
            "This is injected into every Architect prompt for this chapter."
        )
    )
    subtopics: list[SubtopicImport] = Field(
        ..., description="All subtopics in order.", min_length=1
    )


@router.post(
    "/chapterization/{chapter_id}",
    summary="Import chapterization.json — sets up chapter arc + all subtopics at once"
)
def import_chapterization(chapter_id: str, data: ChapterizationImport):
    """
    Imports a full chapter: goal, arc, and all subtopics in one JSON.
    If the chapter already exists, it is overwritten.
    Subtopic IDs are auto-generated from the number (e.g. '1.3.2' → '1_3_2').
    """
    subtopics = []
    for sub in data.subtopics:
        subtopics.append({
            "subtopic_id": sub.number.replace(".", "_"),
            "number": sub.number,
            "title": sub.title,
            "goal": sub.goal,
            "position_in_argument": sub.position_in_argument,
        })

    record = {
        "chapter_id": chapter_id,
        "number": data.number,
        "title": data.title,
        "goal": data.goal,
        "chapter_arc": data.chapter_arc,
        "subtopics": subtopics,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    storage.write_chapter(chapter_id, record)

    return {
        "imported": "chapter",
        "chapter_id": chapter_id,
        "title": data.title,
        "subtopics_created": len(subtopics),
        "chapter_arc_set": True,
        "arc_word_count": len(data.chapter_arc.split()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE.JSON SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class SourceChapterImport(BaseModel):
    """One chapter/section of the external work."""
    label: str = Field(
        ...,
        description="Short label Claude sees in prompts. e.g. 'Sharma Ch.2'"
    )
    title: str = Field(..., description="Full chapter/section title")
    page_range: Optional[str] = Field(None, description="e.g. '45–89'")
    file_name: Optional[str] = Field(None, description="e.g. 'sharma_2003_ch2.pdf'")

    # Index card fields — extracted via NotebookLM, reviewed by you
    key_claims: list[str] = Field(
        ...,
        description="2–5 specific claims this chapter makes.",
        min_length=1
    )
    themes: list[str] = Field(
        ...,
        description="Snake_case theme tags. e.g. ['nationalist_idealization']",
        min_length=1
    )
    time_period_covered: Optional[str] = None
    relevant_subtopics: list[str] = Field(
        default_factory=list,
        description="Your subtopic IDs this chapter supports. e.g. ['1_3_2', '1_3_3']"
    )
    limitations: Optional[str] = Field(
        None,
        description="What this chapter cannot support. Feeds 'Do Not Include' in Task.md."
    )
    notable_authors_cited: list[str] = Field(default_factory=list)


class SourceImport(BaseModel):
    """
    Schema for source.json — one file per external work.
    Generate with /prompts/generate_source_json.txt
    Workflow: upload PDF chapters to NotebookLM → extract structured summary
    → review and correct → import here.
    """
    # Work-level metadata
    title: str
    author: str
    year: Optional[int] = None
    source_type: str = Field(
        ...,
        description="One of: thesis_chapter, book_chapter, journal_article, book, report, other"
    )
    institution_or_publisher: Optional[str] = None
    description: Optional[str] = Field(
        None,
        description="Why you are using this work. How it serves your thesis."
    )
    work_summary: Optional[str] = Field(
        None,
        description=(
            "2–4 sentence summary of the whole work's argument. "
            "Stored for reference, not injected into prompts."
        )
    )

    # Per-chapter index cards
    chapters: list[SourceChapterImport] = Field(
        ..., description="One entry per PDF/chapter you have downloaded.", min_length=1
    )


@router.post("/source", summary="Import source.json — creates group + all sources + index cards in one upload")
def import_source(data: SourceImport):
    """
    Imports a complete external work:
      1 SourceGroup + N Sources + N IndexCards in one request.

    Workflow:
      1. Upload PDF chapters to NotebookLM
      2. Use the extraction prompt (/prompts/generate_source_json.txt) to get source.json
      3. Review and correct key_claims and limitations
      4. POST here
    """
    import uuid

    valid_types = {"thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"}
    if data.source_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"source_type must be one of: {', '.join(valid_types)}"
        )

    group_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()

    # Write group metadata
    group_record = {
        "group_id": group_id,
        "title": data.title,
        "author": data.author,
        "year": data.year,
        "source_type": data.source_type,
        "institution_or_publisher": data.institution_or_publisher,
        "description": data.description,
        "work_summary": data.work_summary,
        "created_at": now,
        "updated_at": now,
    }
    storage.write_source_group(group_id, group_record)

    # Write each chapter as a Source + IndexCard
    created_sources = []
    for ch in data.chapters:
        source_id = str(uuid.uuid4())[:8]
        source_record = {
            "source_id": source_id,
            "group_id": group_id,
            "label": ch.label,
            "title": ch.title,
            "chapter_or_section": ch.title,
            "page_range": ch.page_range,
            "file_name": ch.file_name,
            "file_path": None,
            "index_card": None,
            "has_index_card": False,
            "created_at": now,
            "updated_at": now,
        }
        # Attach index card inline
        index_card = {
            "key_claims": ch.key_claims,
            "themes": ch.themes,
            "time_period_covered": ch.time_period_covered,
            "relevant_subtopics": ch.relevant_subtopics,
            "limitations": ch.limitations,
            "notable_authors_cited": ch.notable_authors_cited,
            "your_notes": None,
            "created_at": now,
            "updated_at": now,
        }
        source_record["index_card"] = index_card
        source_record["has_index_card"] = True
        storage.write_source(group_id, source_id, source_record)
        created_sources.append({"source_id": source_id, "label": ch.label})

    return {
        "imported": "source",
        "group_id": group_id,
        "title": data.title,
        "author": data.author,
        "sources_created": len(created_sources),
        "sources": created_sources,
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

    # Readiness checks
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