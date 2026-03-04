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

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from datetime import datetime
from services import storage

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
def import_thesis(data: ThesisImport):
    record = data.model_dump()
    record["updated_at"] = datetime.utcnow().isoformat()
    storage.write_synopsis(record)
    
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

def _normalize_source_chapter(ch: dict) -> dict:
    """
    Maps alternative field names from NotebookLM output to SPO's canonical schema.
    This makes the importer tolerant of reasonable field name variants so that
    minor differences in what NotebookLM produces don't cause import failures.

    Canonical field         ← Accepted alternatives
    ─────────────────────────────────────────────────
    file_name               ← file, filename, pdf, pdf_name
    title                   ← chapter_title, name, section_title
    label                   ← (auto-generated from file_name or title if missing)
    time_period_covered     ← time_period, period, historical_period
    notable_authors_cited   ← citations, cited_authors, authors_cited, scholars
    key_claims              ← claims, main_claims, arguments
    themes                  ← theme, tags, keywords
    limitations             ← limitation, constraints, cannot_support
    """
    c = dict(ch)  # don't mutate original

    # file_name
    for alt in ("file", "filename", "pdf", "pdf_name"):
        if alt in c and "file_name" not in c:
            c["file_name"] = c.pop(alt)
            break

    # title
    for alt in ("chapter_title", "name", "section_title"):
        if alt in c and "title" not in c:
            c["title"] = c.pop(alt)
            break

    # label — auto-generate if absent
    if "label" not in c or not c["label"]:
        fname = c.get("file_name", "")
        title = c.get("title", "")
        # Use stem of filename, or truncated title
        if fname:
            stem = fname.replace(".pdf", "").replace("_", " ").title()
            c["label"] = stem[:30]
        elif title:
            c["label"] = title[:30]
        else:
            c["label"] = "Unlabelled"

    # time_period_covered
    for alt in ("time_period", "period", "historical_period"):
        if alt in c and "time_period_covered" not in c:
            c["time_period_covered"] = c.pop(alt)
            break

    # notable_authors_cited
    for alt in ("citations", "cited_authors", "authors_cited", "scholars"):
        if alt in c and "notable_authors_cited" not in c:
            c["notable_authors_cited"] = c.pop(alt)
            break

    # key_claims
    for alt in ("claims", "main_claims", "arguments"):
        if alt in c and "key_claims" not in c:
            c["key_claims"] = c.pop(alt)
            break

    # themes — also accept a single string (split on comma)
    for alt in ("theme", "tags", "keywords"):
        if alt in c and "themes" not in c:
            c["themes"] = c.pop(alt)
            break
    if isinstance(c.get("themes"), str):
        c["themes"] = [t.strip() for t in c["themes"].split(",") if t.strip()]

    # limitations — also accept list (join to string)
    for alt in ("limitation", "constraints", "cannot_support"):
        if alt in c and "limitations" not in c:
            c["limitations"] = c.pop(alt)
            break
    if isinstance(c.get("limitations"), list):
        c["limitations"] = " ".join(c["limitations"])
    # ── Coerce null values to defaults (Pydantic defaults only apply for absent keys) ──
    if c.get("title") is None:
        c["title"] = "Untitled Chapter"
    if c.get("label") is None or not c.get("label"):
        c["label"] = c.get("title", "Unlabelled")[:30]
    if not c.get("key_claims"):
        c["key_claims"] = ["No specific claims extracted."]
    if not c.get("themes"):
        c["themes"] = ["uncategorized"]

    # ── Junk drawer: sweep unrecognized keys into additional ─────────────
    CANONICAL_KEYS = {
        "label", "title", "page_range", "file_name",
        "key_claims", "themes", "time_period_covered",
        "relevant_subtopics", "limitations", "notable_authors_cited",
    }
    extras = []
    for k in list(c.keys()):
        if k not in CANONICAL_KEYS:
            val = c.pop(k)
            if val is not None and val != "" and val != []:
                extras.append(f"[{k.upper()}]: {val}")
    if extras:
        existing = c.get("additional") or ""
        separator = "\n" if existing else ""
        c["additional"] = (existing + separator + "\n".join(extras)).strip()

    return c

class SourceChapterImport(BaseModel):
    """One chapter/section of the external work."""
    label: str = Field(
        default="Unlabelled",
        description="Short label Claude sees in prompts. e.g. 'Sharma Ch.2'"
    )
    title: str = Field(default="Untitled Chapter", description="Full chapter/section title")
    page_range: Optional[str] = Field(None, description="e.g. '45–89'")
    file_name: Optional[str] = Field(None, description="e.g. 'sharma_2003_ch2.pdf'")

    # Index card fields — extracted via NotebookLM, reviewed by you
    key_claims: list[str] = Field(
        default_factory=lambda: ["No specific claims extracted."],
        description="2–5 specific claims this chapter makes.",
    )
    themes: list[str] = Field(
        default_factory=lambda: ["uncategorized"],
        description="Snake_case theme tags. e.g. ['nationalist_idealization']",
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
    additional: Optional[str] = Field(None, description="Extra fields swept from JSON import that didn't match the schema.")


class SourceImport(BaseModel):
    """
    Schema for source.json — one file per external work.
    Generate with /prompts/generate_source_json.txt
    Workflow: upload PDF chapters to NotebookLM → extract structured summary
    → review and correct → import here.
    """
    # Work-level metadata
    title: str = Field(default="Untitled Work")
    author: str = Field(default="Unknown Author")
    year: Optional[int] = None
    source_type: str = Field(
        default="other",
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
        default_factory=list, description="One entry per PDF/chapter you have downloaded."
    )
    additional: Optional[str] = Field(None, description="Extra work-level fields from JSON import.")


@router.post("/source", summary="Import source.json — creates group + all sources + index cards in one upload")
def import_source(data: dict = Body(...)):
    """
    Imports a complete external work:
      1 SourceGroup + N Sources + N IndexCards in one request.

    Accepts raw dict, normalizes alternative field names from NotebookLM
    output via _normalize_source_chapter(), then validates with Pydantic.
    """
    import uuid

    # Normalize chapter fields before Pydantic validation
    if "chapters" in data:
        data["chapters"] = [_normalize_source_chapter(ch) for ch in data["chapters"]]

    # ── Work-level junk drawer: sweep extra keys into additional ──────────
    WORK_CANONICAL_KEYS = {
        "title", "author", "year", "source_type",
        "institution_or_publisher", "description", "work_summary", "chapters",
    }
    extras = []
    for k in list(data.keys()):
        if k not in WORK_CANONICAL_KEYS:
            val = data.pop(k)
            if val is not None and val != "" and val != []:
                extras.append(f"[{k.upper()}]: {val}")
    if extras:
        existing = data.get("additional") or ""
        separator = "\n" if existing else ""
        data["additional"] = (existing + separator + "\n".join(extras)).strip()

    # ── Coerce null values to defaults ────────────────────────────────────
    if data.get("title") is None:
        data["title"] = "Untitled Work"
    if data.get("author") is None:
        data["author"] = "Unknown Author"
    if not data.get("source_type"):
        data["source_type"] = "other"

    try:
        data = SourceImport(**data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

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
        "additional": data.additional,
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
            "additional": ch.additional,
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