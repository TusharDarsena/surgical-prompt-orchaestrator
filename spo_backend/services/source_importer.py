"""
Source Importer Service
-----------------------
Shared models and import logic extracted from routers/importer.py so that
routers/drive.py can import them at the top level without creating a circular
dependency (drive → importer → storage, with no back-edge to drive).

Both routers/importer.py (re-exports) and routers/drive.py use this module.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ValidationError
from fastapi import HTTPException
from services import storage


# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

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
        description="What this chapter cannot support. Feeds 'Do Not Include' in compiled prompts."
    )
    notable_authors_cited: list[str] = Field(default_factory=list)
    additional: Optional[str] = Field(None, description="Extra fields swept from JSON import that didn't match the schema.")


class SourceImport(BaseModel):
    """
    Schema for source.json — one file per external work.
    Generate with /prompts/generate_source_json.txt
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


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION
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

    # Coerce null values to defaults
    if c.get("title") is None:
        c["title"] = "Untitled Chapter"
    if c.get("label") is None or not c.get("label"):
        c["label"] = c.get("title", "Unlabelled")[:30]
    if not c.get("key_claims"):
        c["key_claims"] = ["No specific claims extracted."]
    if not c.get("themes"):
        c["themes"] = ["uncategorized"]

    # Junk drawer: sweep unrecognized keys into additional
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


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-IMPORT
# ══════════════════════════════════════════════════════════════════════════════

_VALID_SOURCE_TYPES = {"thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"}


def do_auto_import(data: dict, thesis_id: str = "") -> tuple[dict | None, str | None]:
    """
    Takes a raw source dict (already parsed from JSON), normalizes it,
    validates with Pydantic, then writes a SourceGroup + Sources + IndexCards
    to storage.

    Returns (result_dict, None) on success, or (None, error_message) on failure.
    """
    # Normalize chapters
    if "chapters" in data:
        data = dict(data)  # don't mutate caller's dict
        data["chapters"] = [_normalize_source_chapter(ch) for ch in data["chapters"]]

    # Work-level junk drawer
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

    # Coerce null values to defaults
    if data.get("title") is None:
        data["title"] = "Untitled Work"
    if data.get("author") is None:
        data["author"] = "Unknown Author"
    if not data.get("source_type"):
        data["source_type"] = "other"

    try:
        validated = SourceImport(**data)
    except ValidationError as e:
        return None, f"Validation failed: {e.errors()}"

    if validated.source_type not in _VALID_SOURCE_TYPES:
        return None, f"source_type must be one of: {', '.join(_VALID_SOURCE_TYPES)}"

    group_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()

    group_record = {
        "group_id": group_id,
        "title": validated.title,
        "author": validated.author,
        "year": validated.year,
        "source_type": validated.source_type,
        "institution_or_publisher": validated.institution_or_publisher,
        "description": validated.description,
        "work_summary": validated.work_summary,
        "additional": validated.additional,
        "created_at": now,
        "updated_at": now,
    }
    storage.write_source_group(group_id, group_record, thesis_id=thesis_id)

    created_sources = []
    for ch in validated.chapters:
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
        storage.write_source(group_id, source_id, source_record, thesis_id=thesis_id)
        created_sources.append({"source_id": source_id, "label": ch.label})

    return {
        "group_id": group_id,
        "title": validated.title,
        "author": validated.author,
        "sources_created": len(created_sources),
        "sources": created_sources,
    }, None
