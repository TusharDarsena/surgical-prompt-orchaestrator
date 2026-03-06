"""
Sections Router
---------------
Stores and retrieves NotebookLM draft output per subtopic.
Drafts are separate from consistency summaries — both can exist for the same subtopic.

Endpoints:
    GET  /sections/{chapter_id}/{subtopic_id}/draft   ← load saved draft
    POST /sections/{chapter_id}/{subtopic_id}/draft   ← save or overwrite draft
    DELETE /sections/{chapter_id}/{subtopic_id}/draft ← clear draft
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from services import storage

router = APIRouter(prefix="/sections", tags=["Section Drafts"])


class DraftSaveRequest(BaseModel):
    text: str


@router.get("/{chapter_id}/{subtopic_id}/draft", summary="Load saved draft for a subtopic")
def get_draft(chapter_id: str, subtopic_id: str):
    draft = storage.read_section_draft(chapter_id, subtopic_id)
    if not draft:
        raise HTTPException(status_code=404, detail="No draft saved for this subtopic.")
    return draft


@router.post("/{chapter_id}/{subtopic_id}/draft", summary="Save or overwrite draft for a subtopic")
def save_draft(chapter_id: str, subtopic_id: str, req: DraftSaveRequest):
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="Draft text cannot be empty.")
    record = {
        "chapter_id": chapter_id,
        "subtopic_id": subtopic_id,
        "text": req.text,
        "updated_at": datetime.utcnow().isoformat(),
    }
    return storage.write_section_draft(chapter_id, subtopic_id, record)


@router.delete("/{chapter_id}/{subtopic_id}/draft", summary="Delete draft for a subtopic")
def delete_draft(chapter_id: str, subtopic_id: str):
    deleted = storage.delete_section_draft(chapter_id, subtopic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No draft found to delete.")
    return {"deleted": True, "subtopic_id": subtopic_id}
