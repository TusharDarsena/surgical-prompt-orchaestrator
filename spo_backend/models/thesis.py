"""
Thesis Context Models
---------------------
The hierarchy:
  ThesisSynopsis  ← the master argument, compressed from your synopsis document
      └── Chapter ← what this chapter proves + its arc (NEW)
              └── Subtopic ← one NotebookLM writing session
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ThesisSynopsis(BaseModel):
    """
    Populated via JSON import (POST /import/thesis).
    Only core_argument, theoretical_frameworks, and temporal_scope
    are injected into Architect prompts.
    The rest is stored for your reference.
    """
    # ── Injected into every Architect Mega-Prompt ──────────────────────────────
    title: str
    author: str
    field: str
    central_argument: str = Field(
        ..., description="The single core argument of the entire thesis. 2–4 sentences."
    )
    theoretical_frameworks: list[str] = Field(
        default_factory=list,
        description="e.g. ['Postcolonial feminism', 'New Historicism']"
    )
    temporal_scope: Optional[str] = Field(
        None, description="e.g. '1947–1990'"
    )

    # ── Stored for reference, NOT injected into prompts ────────────────────────
    research_questions: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    methodology: Optional[str] = None
    key_authors: list[str] = Field(default_factory=list)
    central_themes: list[str] = Field(default_factory=list)
    chapter_structure_overview: Optional[str] = None
    scope_and_limits: Optional[str] = None

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Subtopic(BaseModel):
    subtopic_id: str = Field(..., description="e.g. '1_3_2'")
    number: str = Field(..., description="e.g. '1.3.2'")
    title: str
    goal: str
    position_in_argument: Optional[str] = None


class Chapter(BaseModel):
    chapter_id: str
    number: int
    title: str
    goal: str
    chapter_arc: Optional[str] = Field(
        None,
        description=(
            "150–200 words. How all subtopics of this chapter connect argumentatively. "
            "Injected into every Architect prompt for this chapter as Section 2. "
            "This is what prevents Claude from generating generic Task.md output — "
            "it tells Claude the exact argumentative role each subtopic must play "
            "within the chapter's larger movement."
        )
    )
    subtopics: list[Subtopic] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Request models (manual form path — still fully supported) ──────────────────

class SynopsisCreateRequest(BaseModel):
    title: str
    author: str
    field: str
    central_argument: str
    theoretical_frameworks: list[str] = []
    temporal_scope: Optional[str] = None
    research_questions: list[str] = []
    objectives: list[str] = []
    methodology: Optional[str] = None
    key_authors: list[str] = []
    central_themes: list[str] = []
    chapter_structure_overview: Optional[str] = None
    scope_and_limits: Optional[str] = None


class SynopsisUpdateRequest(BaseModel):
    central_argument: Optional[str] = None
    theoretical_frameworks: Optional[list[str]] = None
    temporal_scope: Optional[str] = None
    scope_and_limits: Optional[str] = None
    chapter_structure_overview: Optional[str] = None


class ChapterCreateRequest(BaseModel):
    number: int
    title: str
    goal: str
    chapter_arc: Optional[str] = None


class SubtopicCreateRequest(BaseModel):
    number: str
    title: str
    goal: str
    position_in_argument: Optional[str] = None


class SubtopicUpdateRequest(BaseModel):
    title: Optional[str] = None
    goal: Optional[str] = None
    position_in_argument: Optional[str] = None
    chapter_arc: Optional[str] = None  # allow patching arc manually