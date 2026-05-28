"""
Source Importer Service
-----------------------
Responsibility :
Data Models: It defines exactly what a valid source looks like using Pydantic (SourceImport, SourceChapterImport).
Data Normalization: _normalize_source_chapter function, which acts as a "translation layer" to map messy, varied JSON inputs (like "filename" vs. "pdf_name") into a strict, canonical format.
Database Operations: do_auto_import function contains logic to create IDs, structure the database records, and write them to storage.
Zero Web Routing: This file has absolutely no FastAPI @router endpoints. It just processes data.

Shared models and import logic extracted from routers/importer.py so that
routers/drive.py can import them at the top level without creating a circular
dependency (drive → importer → storage, with no back-edge to drive).

Both routers/importer.py (re-exports) and routers/drive.py use this module.
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, model_validator
from fastapi import HTTPException
from services import storage


# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

class SourceChapterImport(BaseModel):
    """One chapter/section of the external work."""
    model_config = {"extra": "allow"}

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

    @model_validator(mode='after')
    def gather_extra_fields(self) -> 'SourceChapterImport':
        extras = []
        if self.__pydantic_extra__:
            for k, val in self.__pydantic_extra__.items():
                if val is not None and val != "" and val != []:
                    extras.append(f"[{k.upper()}]: {val}")
        if extras:
            existing = self.additional or ""
            separator = "\n" if existing else ""
            self.additional = (existing + separator + "\n".join(extras)).strip()
        return self


class SourceImport(BaseModel):
    """
    Schema for source.json — one file per external work.
    Generate with /prompts/generate_source_json.txt
    """
    model_config = {"extra": "allow"}

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

    @model_validator(mode='after')
    def gather_extra_fields(self) -> 'SourceImport':
        extras = []
        if self.__pydantic_extra__:
            for k, val in self.__pydantic_extra__.items():
                if val is not None and val != "" and val != []:
                    extras.append(f"[{k.upper()}]: {val}")
        if extras:
            existing = self.additional or ""
            separator = "\n" if existing else ""
            self.additional = (existing + separator + "\n".join(extras)).strip()
        return self


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

    # Strip all empty values so Pydantic's default_factory triggers correctly for any field
    keys_to_remove = [k for k, v in c.items() if v in (None, [], "")]
    for k in keys_to_remove:
        c.pop(k)

    return c


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-IMPORT
# ══════════════════════════════════════════════════════════════════════════════

_VALID_SOURCE_TYPES = {"thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"}


def do_auto_import(data: dict, thesis_id: str = "", scan_key: str = "") -> tuple[dict | None, str | None]:
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

    # Strip all empty values so Pydantic defaults apply for any field
    keys_to_remove = [k for k, v in data.items() if v in (None, [], "") and k != "chapters"]
    for k in keys_to_remove:
        data.pop(k)

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
        "scan_key": scan_key or None,
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
