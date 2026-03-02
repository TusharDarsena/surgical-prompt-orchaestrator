"""
Notes Router
------------
Free-text notes attached to any entity: thesis, source group, source, or chapter.

This solves the "index card is too much work upfront" problem.
Workflow:
  1. Read a source → paste your raw notes here immediately
  2. Later, convert the note into a structured index card when you need it for a prompt
  3. Notes are always available as a reference, even before the index card exists

URL pattern: /notes/{scope}/{entity_id}/
  scope = thesis | source_group | source | chapter
  entity_id = the ID of that thing (or "main" for the thesis)
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime
import uuid

from models.notes import NoteCreateRequest, NoteUpdateRequest
from services import storage

router = APIRouter(prefix="/notes", tags=["Notes"])


@router.post("/{scope}/{entity_id}", summary="Add a free-text note to any entity")
def create_note(scope: str, entity_id: str, req: NoteCreateRequest):
    """
    Paste anything here — reading impressions, copied text from the PDF,
    argument ideas, gaps you notice. No structure required.

    Examples:
      POST /notes/source_group/abc123   ← overall note on a thesis/book
      POST /notes/source/def456        ← note on one chapter/PDF
      POST /notes/chapter/chapter_01   ← note on YOUR chapter 1
      POST /notes/thesis/main          ← general thesis research note
    """
    _validate_scope(scope)
    short_id = str(uuid.uuid4())[:6]
    note_id = f"{entity_id}_{short_id}"
    data = {
        "note_id": note_id,
        "scope": scope,
        "entity_id": entity_id,
        "label": req.label,
        "content": req.content,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    return storage.write_note(scope, note_id, data)


@router.get("/{scope}/{entity_id}", summary="List all notes for an entity")
def list_notes(scope: str, entity_id: str):
    _validate_scope(scope)
    notes = storage.list_notes(scope, entity_id)
    return {"entity_id": entity_id, "scope": scope, "notes": notes, "count": len(notes)}


@router.get("/{scope}/{entity_id}/{note_id}", summary="Get a specific note")
def get_note(scope: str, entity_id: str, note_id: str):
    _validate_scope(scope)
    data = storage.read_note(scope, note_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found.")
    return data


@router.patch("/{scope}/{entity_id}/{note_id}", summary="Update a note")
def update_note(scope: str, entity_id: str, note_id: str, req: NoteUpdateRequest):
    _validate_scope(scope)
    data = storage.read_note(scope, note_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found.")
    if req.label is not None:
        data["label"] = req.label
    if req.content is not None:
        data["content"] = req.content
    return storage.write_note(scope, note_id, data)


@router.delete("/{scope}/{entity_id}/{note_id}", summary="Delete a note")
def delete_note(scope: str, entity_id: str, note_id: str):
    _validate_scope(scope)
    if not storage.delete_note(scope, note_id):
        raise HTTPException(status_code=404, detail=f"Note '{note_id}' not found.")
    return {"deleted": note_id}


def _validate_scope(scope: str):
    valid = {"thesis", "source_group", "source", "chapter"}
    if scope not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scope '{scope}'. Must be one of: {', '.join(valid)}"
        )
