"""
Notes Models
------------
Free-text notes for when you don't want to fill structured index card fields.

Use cases:
  - You've read a source and want to dump your thoughts before structuring them
  - You have overall notes about a thesis you're using as a source
  - Chapter-level notes for a multi-chapter work (before breaking into index cards)
  - Your own thesis writing notes per chapter

Notes live alongside the structured data but are never injected into prompts
automatically — they're YOUR scratch pad. When you're ready, the compiler
endpoint can optionally include a note as a raw block.

Storage location: spo_data/notes/{scope}/{id}.json
  scope: "thesis" | "source_group" | "source" | "chapter"
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

NoteScope = Literal["thesis", "source_group", "source", "chapter"]


class Note(BaseModel):
    """
    A free-text note attached to any entity in the system.
    Write whatever you want here — reading impressions, argument ideas,
    connections you notice, things to follow up.
    """
    note_id: str
    scope: NoteScope = Field(..., description="What this note is about")
    entity_id: str = Field(
        ...,
        description=(
            "ID of the entity this note belongs to. "
            "e.g. group_id, source_id, chapter_id, or 'main' for thesis-level notes."
        )
    )
    label: Optional[str] = Field(
        None,
        description="Short title for the note. e.g. 'Overall impressions', 'Chapter 3 gaps'"
    )
    content: str = Field(
        ...,
        description=(
            "The note itself. Plain text, no structure required. "
            "Paste your reading notes, paste text you copied from the PDF, "
            "write stream-of-consciousness — whatever is useful."
        )
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NoteCreateRequest(BaseModel):
    label: Optional[str] = None
    content: str


class NoteUpdateRequest(BaseModel):
    label: Optional[str] = None
    content: Optional[str] = None
