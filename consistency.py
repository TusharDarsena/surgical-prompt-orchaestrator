"""
Consistency Chain Models
------------------------
The mechanism that prevents Claude and NotebookLM from "resetting" their logic
between subtopics. Without this, each section feels like a fresh essay with
no memory of what was argued before.

How it works:
  After NotebookLM writes subtopic 1.3.1, you save a brief summary of what
  was argued. When writing 1.3.2, your app injects that summary as
  "Previous Section Context" into the NotebookLM prompt.

This is the consistency layer your document describes needing.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SectionSummary(BaseModel):
    """
    A brief record of what was argued in a completed subtopic.
    Written by you (or Claude) after NotebookLM produces the draft.
    Injected into the NEXT subtopic's NotebookLM prompt.
    """
    chapter_id: str
    subtopic_id: str
    subtopic_number: str = Field(..., description="e.g. '1.3.1'")
    subtopic_title: str

    # The consistency payload — this is what gets injected
    core_argument_made: str = Field(
        ...,
        description=(
            "What was the central argument of this section? 2-3 sentences. "
            "Written after the draft is approved. "
            "e.g. 'Established that pre-independence male authors constructed female "
            "characters as nationalist symbols, creating a gap between literary representation "
            "and lived experience. Used Sharma Ch.2 and Nair 1992 as primary evidence.'"
        )
    )
    key_terms_established: list[str] = Field(
        default_factory=list,
        description=(
            "Terms or concepts defined in this section that the next section should "
            "use consistently. e.g. ['nationalist idealization', 'representational gap']"
        )
    )
    sources_used: list[str] = Field(
        default_factory=list,
        description="Source labels used. e.g. ['Sharma Ch.2', 'Nair 1992']"
    )
    what_next_section_must_build_on: Optional[str] = Field(
        None,
        description=(
            "Explicit bridge instruction for the next subtopic. "
            "e.g. 'Next section should use the concept of nationalist idealization "
            "established here as the baseline from which feminist writing departed.'"
        )
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SectionSummaryCreateRequest(BaseModel):
    subtopic_number: str
    subtopic_title: str
    core_argument_made: str
    key_terms_established: list[str] = []
    sources_used: list[str] = []
    what_next_section_must_build_on: Optional[str] = None
