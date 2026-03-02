"""
Source Library Models
---------------------
These models represent your external source materials — the PDFs and books
you are reading and drawing arguments from.

The hierarchy is:
  SourceGroup  (a complete work: e.g. "Sharma 2003 PhD Thesis")
      └── Source  (one document/chapter from that work)
              └── IndexCard  (YOUR human-written summary of what it contains)

Why separate SourceGroup from Source?
  A PhD thesis has 6 chapters. A book has 12 chapters. You upload them separately
  as PDFs but they belong to the same intellectual work. The SourceGroup keeps
  that relationship intact so when you need "everything from Sharma 2003"
  you can pull all its sources at once.

Why is IndexCard human-written and not AI-generated?
  Because Claude generating index cards from PDFs will hallucinate or miss
  your specific argumentative needs. YOU decide what matters in each source.
  The index card is your curation layer — the most valuable asset in this system.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid


SourceType = Literal[
    "thesis_chapter",
    "book_chapter",
    "journal_article",
    "book",
    "report",
    "other"
]


class IndexCard(BaseModel):
    """
    The core intelligence unit of SPO.

    This is what gets injected into the Architect Mega-Prompt as 'Source Profile'.
    Claude reads these cards — not the raw PDFs — to generate grounded Task.md files.

    Write these carefully. A good index card has:
    - Specific claims (not "discusses feminism" but "argues that pre-1947 female
      characters in male-authored texts were idealized as nationalist symbols")
    - Named themes that map to your subtopics
    - Honest limitations (what the source CANNOT support)
    """
    # Core content — these are injected into prompts
    key_claims: list[str] = Field(
        ...,
        description=(
            "2-5 specific, concrete claims this source makes. "
            "Be precise. Avoid generic statements. "
            "Good: 'Argues partition trauma redirected female identity from nation to self.' "
            "Bad: 'Discusses women in post-partition literature.'"
        ),
        min_length=1
    )
    themes: list[str] = Field(
        ...,
        description=(
            "Thematic tags for filtering. e.g. ['feminist_literary_history', "
            "'postcolonial_identity', 'partition_trauma']. "
            "Use snake_case. These help the app suggest relevant sources per subtopic."
        ),
        min_length=1
    )
    time_period_covered: Optional[str] = Field(
        None,
        description="Historical period the source focuses on. e.g. '1947-1980'"
    )
    relevant_subtopics: list[str] = Field(
        default_factory=list,
        description=(
            "Which of YOUR subtopic IDs (e.g. '1_3_2') is this source useful for? "
            "Fill this as you read. Drives auto-suggestion of sources when compiling prompts."
        )
    )
    limitations: Optional[str] = Field(
        None,
        description=(
            "What can this source NOT support? What arguments would be a stretch? "
            "e.g. 'Focuses only on Bengali literature, cannot support claims about "
            "pan-Indian feminist movement.' This feeds the Task.md 'Do Not Include' section."
        )
    )
    notable_authors_cited: list[str] = Field(
        default_factory=list,
        description="Key scholars/authors cited in this source. For academic credibility tracking."
    )
    your_notes: Optional[str] = Field(
        None,
        description=(
            "Private reading notes. NOT injected into prompts. "
            "For your own reference while writing."
        )
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Source(BaseModel):
    """
    One document — typically one PDF file or one chapter of a larger work.
    """
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    group_id: str = Field(..., description="Parent SourceGroup ID")

    # Identity
    label: str = Field(
        ...,
        description=(
            "Short label for prompt injection. e.g. 'Source A', 'Sharma Ch.3', 'Nair 1992'. "
            "This is the name Claude sees in the Architect Mega-Prompt."
        )
    )
    title: str = Field(..., description="Full title of this document/chapter")
    chapter_or_section: Optional[str] = Field(
        None,
        description="e.g. 'Chapter 3: The Nationalist Imagination' or 'Section 2.4'"
    )
    page_range: Optional[str] = Field(
        None,
        description="e.g. '45-89' — for citing in your thesis"
    )

    # File reference (no upload, just path tracking)
    file_path: Optional[str] = Field(
        None,
        description="Absolute path to PDF on your local drive. For NotebookLM upload reference."
    )
    file_name: Optional[str] = Field(
        None,
        description="e.g. 'sharma_2003_ch3.pdf'"
    )

    # The intelligence layer
    index_card: Optional[IndexCard] = Field(
        None,
        description="Your curated summary. Fill this after reading the source."
    )

    has_index_card: bool = Field(
        default=False,
        description="Quick flag — False means this source is not yet ready for prompt injection."
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SourceGroup(BaseModel):
    """
    A complete intellectual work that may be broken into multiple Source documents.

    Examples:
      - A PhD thesis (6 chapter PDFs → 1 SourceGroup, 6 Sources)
      - A book (uploaded chapter by chapter → 1 SourceGroup, N Sources)
      - A single journal article (1 SourceGroup, 1 Source)

    This keeps provenance intact — you always know all Sources from
    'Sharma 2003' belong together.
    """
    group_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = Field(..., description="Full title of the work")
    author: str = Field(..., description="Author(s) name(s)")
    year: Optional[int] = Field(None, description="Publication year")
    source_type: SourceType = Field(..., description="Type of source material")
    institution_or_publisher: Optional[str] = Field(
        None,
        description="e.g. 'JNU', 'Oxford University Press'"
    )
    description: Optional[str] = Field(
        None,
        description=(
            "Brief note on what this work is about and WHY you are using it. "
            "e.g. 'Sharma's thesis on pre-independence Bengali women writers. "
            "Primary source for Chapter 1 historical background.'"
        )
    )
    sources: list[Source] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def ready_sources(self) -> list[Source]:
        """Sources that have index cards and are ready for prompt injection."""
        return [s for s in self.sources if s.has_index_card]

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def ready_count(self) -> int:
        return len(self.ready_sources)


# --- Request models ---

class SourceGroupCreateRequest(BaseModel):
    title: str
    author: str
    year: Optional[int] = None
    source_type: SourceType
    institution_or_publisher: Optional[str] = None
    description: Optional[str] = None


class SourceGroupUpdateRequest(BaseModel):
    description: Optional[str] = None
    institution_or_publisher: Optional[str] = None


class SourceCreateRequest(BaseModel):
    label: str
    title: str
    chapter_or_section: Optional[str] = None
    page_range: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None


class SourceUpdateRequest(BaseModel):
    label: Optional[str] = None
    title: Optional[str] = None
    chapter_or_section: Optional[str] = None
    page_range: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None


class IndexCardCreateRequest(BaseModel):
    key_claims: list[str]
    themes: list[str]
    time_period_covered: Optional[str] = None
    relevant_subtopics: list[str] = []
    limitations: Optional[str] = None
    notable_authors_cited: list[str] = []
    your_notes: Optional[str] = None


class IndexCardUpdateRequest(BaseModel):
    key_claims: Optional[list[str]] = None
    themes: Optional[list[str]] = None
    time_period_covered: Optional[str] = None
    relevant_subtopics: Optional[list[str]] = None
    limitations: Optional[str] = None
    notable_authors_cited: Optional[list[str]] = None
    your_notes: Optional[str] = None
