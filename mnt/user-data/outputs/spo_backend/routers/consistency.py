"""
Consistency Chain Router
------------------------
Stores and retrieves section summaries that maintain argument continuity
across subtopics.

After writing each section, save a summary here.
The next section's NotebookLM prompt will include this as context.
"""

from fastapi import APIRouter, HTTPException
from models.consistency import SectionSummaryCreateRequest
from services import storage

router = APIRouter(prefix="/consistency", tags=["Consistency Chain"])


@router.post(
    "/{chapter_id}/{subtopic_id}",
    summary="Save summary after completing a subtopic"
)
def save_section_summary(
    chapter_id: str,
    subtopic_id: str,
    req: SectionSummaryCreateRequest
):
    """
    Call this after NotebookLM produces an approved draft.
    The summary becomes the 'Previous Section Context' for the next subtopic.
    """
    data = req.model_dump()
    return storage.write_section_summary(chapter_id, subtopic_id, data)


@router.get(
    "/{chapter_id}",
    summary="Get all section summaries for a chapter (the consistency chain)"
)
def get_chapter_chain(chapter_id: str):
    """
    Returns all completed summaries in order.
    Your app uses this to show the argumentative thread of a chapter so far.
    """
    summaries = storage.list_section_summaries(chapter_id)
    return {
        "chapter_id": chapter_id,
        "chain": summaries,
        "sections_completed": len(summaries)
    }


@router.get(
    "/{chapter_id}/{subtopic_id}",
    summary="Get summary for a specific completed subtopic"
)
def get_section_summary(chapter_id: str, subtopic_id: str):
    data = storage.read_section_summary(chapter_id, subtopic_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"No summary found for subtopic '{subtopic_id}'. "
                   "Complete and save the section first."
        )
    return data


@router.get(
    "/{chapter_id}/previous-for/{subtopic_id}",
    summary="Get the previous section's summary (for injecting into next prompt)"
)
def get_previous_summary(chapter_id: str, subtopic_id: str):
    """
    Key endpoint for the app: before compiling a prompt for subtopic X,
    call this to get the summary of the subtopic written just before X.
    Inject the returned data into your NotebookLM prompt as 'Previous Section Context'.
    """
    chapter = storage.read_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics = chapter.get("subtopics", [])
    ids_in_order = [s["subtopic_id"] for s in subtopics]

    if subtopic_id not in ids_in_order:
        raise HTTPException(status_code=404, detail=f"Subtopic '{subtopic_id}' not in chapter.")

    idx = ids_in_order.index(subtopic_id)
    if idx == 0:
        return {"message": "This is the first subtopic. No previous section context.", "summary": None}

    previous_id = ids_in_order[idx - 1]
    summary = storage.read_section_summary(chapter_id, previous_id)
    if not summary:
        return {
            "message": f"Previous subtopic '{previous_id}' exists but has no saved summary yet.",
            "summary": None
        }
    return {"summary": summary}


@router.delete(
    "/{chapter_id}/{subtopic_id}",
    summary="Delete a section summary (if you need to rewrite)"
)
def delete_section_summary(chapter_id: str, subtopic_id: str):
    if not storage.delete_section_summary(chapter_id, subtopic_id):
        raise HTTPException(status_code=404, detail="Summary not found.")
    return {"deleted": subtopic_id}
