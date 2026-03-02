"""
Thesis Context Models
---------------------
These models hold the "big picture" of your OWN thesis.
Without this context, every prompt Claude generates is blind to your argument.

The hierarchy is:
  ThesisSynopsis  (the master argument of the whole thesis)
      └── Chapter (what this chapter must prove)
              └── Subtopic (the specific section being written)
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ThesisSynopsis(BaseModel):
    """
    The master document. Stored once. Injected into every Architect Mega-Prompt.
    Write this carefully — it is the spine of all generated Task.md files.
    """
    title: str = Field(..., description="Full thesis title")
    author: str = Field(..., description="Your name")
    field: str = Field(..., description="e.g. Indian English Literature")
    central_argument: str = Field(
        ...,
        description=(
            "The single core argument of the entire thesis. "
            "2-4 sentences. This is what the whole thesis is trying to prove."
        )
    )
    theoretical_framework: Optional[str] = Field(
        None,
        description="e.g. Postcolonial feminism, New Historicism"
    )
    scope_and_limits: Optional[str] = Field(
        None,
        description="What the thesis explicitly covers and does NOT cover"
    )
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Subtopic(BaseModel):
    """
    A single subtopic within a chapter. e.g. '1.3.2 Entry of Feminism...'
    This is the unit of work — one subtopic = one Task.md = one NotebookLM session.
    """
    subtopic_id: str = Field(..., description="e.g. 1_3_2")
    number: str = Field(..., description="e.g. 1.3.2")
    title: str = Field(..., description="Full subtopic title")
    goal: str = Field(
        ...,
        description="What must this subtopic argue or establish? 1-2 sentences."
    )
    position_in_argument: Optional[str] = Field(
        None,
        description=(
            "How does this subtopic serve the chapter's argument? "
            "e.g. 'Establishes the historical gap that chapter fills'"
        )
    )


class Chapter(BaseModel):
    """
    One chapter of the thesis. Stores the chapter's specific goal and all its subtopics.
    The chapter goal is injected alongside the synopsis when generating Task.md.
    """
    chapter_id: str = Field(..., description="e.g. chapter_01")
    number: int = Field(..., description="Chapter number")
    title: str = Field(..., description="Full chapter title")
    goal: str = Field(
        ...,
        description=(
            "What must this chapter prove? How does it serve the thesis argument? "
            "3-5 sentences. This is the 'Chapter Goal' injected into the Architect Mega-Prompt."
        )
    )
    subtopics: list[Subtopic] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Request/Response models ---

class SynopsisCreateRequest(BaseModel):
    title: str
    author: str
    field: str
    central_argument: str
    theoretical_framework: Optional[str] = None
    scope_and_limits: Optional[str] = None


class SynopsisUpdateRequest(BaseModel):
    central_argument: Optional[str] = None
    theoretical_framework: Optional[str] = None
    scope_and_limits: Optional[str] = None


class ChapterCreateRequest(BaseModel):
    number: int
    title: str
    goal: str


class SubtopicCreateRequest(BaseModel):
    number: str
    title: str
    goal: str
    position_in_argument: Optional[str] = None


class SubtopicUpdateRequest(BaseModel):
    title: Optional[str] = None
    goal: Optional[str] = None
    position_in_argument: Optional[str] = None
