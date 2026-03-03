"""
Thesis Context Models
---------------------
ThesisSynopsis schema matches the preferred thesis.json structure.

Fields injected into every Architect Mega-Prompt (kept tight):
  - central_argument
  - temporal_scope
  - theoretical_frameworks   (from methodology.theoretical_frameworks)
  - central_themes
  - research_gap

Everything else is stored for reference only.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Nested models for thesis.json sub-objects ──────────────────────────────────

class KeyAuthor(BaseModel):
    author: str
    work: Optional[str] = None
    year: Optional[int] = None
    theme: Optional[str] = None


class Methodology(BaseModel):
    approach: Optional[str] = None
    primary_method: Optional[str] = None
    supporting_methods: list[str] = Field(default_factory=list)
    theoretical_frameworks: list[str] = Field(default_factory=list)
    data_sources: Optional[dict] = None


class TheoreticalPositions(BaseModel):
    feminism_in_india: Optional[str] = None
    postcolonial_feminism: Optional[str] = None
    literature_as_agent: Optional[str] = None


class ChapterStructureEntry(BaseModel):
    chapter: int
    title: str
    focus: Optional[str] = None


class LiteratureReviewFinding(BaseModel):
    author: str
    finding: str


class Significance(BaseModel):
    academic: Optional[str] = None
    practical: Optional[str] = None
    contemporary: Optional[str] = None


# ── Main synopsis model ────────────────────────────────────────────────────────

class ThesisSynopsis(BaseModel):
    # ── Identity ───────────────────────────────────────────────────────────────
    document_type: Optional[str] = None
    title: str
    institution: Optional[str] = None
    researcher: Optional[str] = None       # alias for author
    author: Optional[str] = None           # kept for backward compat
    year: Optional[int] = None
    degree: Optional[str] = None
    field: Optional[str] = None

    # ── INJECTED into every Architect Mega-Prompt ──────────────────────────────
    research_question: Optional[str] = None
    core_argument: str = Field(
        ...,
        description=(
            "The single core argument of the entire thesis. 2–4 sentences. "
            "What the thesis argues and proves, specifically."
        )
    )
    temporal_scope: Optional[str] = None
    research_gap: Optional[str] = Field(
        None,
        description=(
            "What gap in existing scholarship this thesis fills. "
            "Injected into prompts — prevents Claude from writing as if "
            "the thesis is making generic observations already covered elsewhere."
        )
    )
    central_themes: list[str] = Field(
        default_factory=list,
        description="Full descriptive theme strings from the synopsis."
    )

    # ── Methodology (theoretical_frameworks pulled from here for injection) ────
    methodology: Optional[Methodology] = None

    # ── REFERENCE ONLY — not injected ─────────────────────────────────────────
    objectives: list[str] = Field(default_factory=list)
    key_authors_and_works: list[KeyAuthor] = Field(default_factory=list)
    other_authors_mentioned: list[str] = Field(default_factory=list)
    theoretical_positions: Optional[TheoreticalPositions] = None
    chapter_structure: list[ChapterStructureEntry] = Field(default_factory=list)
    expected_outcome: Optional[str] = None
    significance: Optional[Significance] = None
    key_literature_review_findings: list[LiteratureReviewFinding] = Field(default_factory=list)
    scope_and_limits: Optional[str] = None

    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def get_author(self) -> str:
        """Returns researcher or author, whichever is set."""
        return self.researcher or self.author or ""

    def get_theoretical_frameworks(self) -> list[str]:
        """Pull frameworks from methodology object."""
        if self.methodology:
            return self.methodology.theoretical_frameworks
        return []


# ── Chapter models ─────────────────────────────────────────────────────────────

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
            "150–200 words. How all subtopics connect argumentatively. "
            "Injected into every Architect prompt for this chapter as Section 2."
        )
    )
    subtopics: list[Subtopic] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Request models (manual form path) ─────────────────────────────────────────

class SynopsisCreateRequest(BaseModel):
    """Flat request for the manual form path."""
    title: str
    author: str
    field: Optional[str] = None
    central_argument: Optional[str] = None
    core_argument: Optional[str] = None     # accept both field names
    theoretical_frameworks: list[str] = []
    temporal_scope: Optional[str] = None
    research_question: Optional[str] = None
    research_gap: Optional[str] = None
    objectives: list[str] = []
    central_themes: list[str] = []
    scope_and_limits: Optional[str] = None


class SynopsisUpdateRequest(BaseModel):
    core_argument: Optional[str] = None
    central_argument: Optional[str] = None  # backward compat alias
    temporal_scope: Optional[str] = None
    research_gap: Optional[str] = None
    scope_and_limits: Optional[str] = None


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
    chapter_arc: Optional[str] = None