"""
Thesis Context Router
---------------------
Endpoints for managing your OWN thesis structure:
synopsis, chapters, and subtopics.

This is the "big picture" layer — always injected into compiled prompts.
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
import uuid

from models.thesis import (
    ThesisSynopsis, Chapter, Subtopic,
    SynopsisCreateRequest, SynopsisUpdateRequest,
    ChapterCreateRequest, SubtopicCreateRequest, SubtopicUpdateRequest,
)
from services import storage

router = APIRouter(prefix="/thesis", tags=["Thesis Context"])


# --- Synopsis ---

@router.post("/synopsis", response_model=dict, summary="Create or replace thesis synopsis")
def create_synopsis(req: SynopsisCreateRequest, thesis_id: str = Query("")):
    """
    Store the master argument of your thesis.
    Write this once and update it only if your central argument shifts.
    This is injected into every compiled prompt.
    """
    data = req.model_dump()
    data["updated_at"] = datetime.utcnow().isoformat()
    return storage.write_synopsis(data, thesis_id=thesis_id)


@router.get("/synopsis", summary="Get thesis synopsis")
def get_synopsis(thesis_id: str = Query("")):
    data = storage.read_synopsis(thesis_id=thesis_id)
    if not data:
        raise HTTPException(status_code=404, detail="No synopsis found. Create one first.")
    return data


@router.patch("/synopsis", summary="Update thesis synopsis")
def update_synopsis(req: SynopsisUpdateRequest, thesis_id: str = Query("")):
    existing = storage.read_synopsis(thesis_id=thesis_id)
    if not existing:
        raise HTTPException(status_code=404, detail="No synopsis found. Create one first.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    existing.update(updates)
    return storage.write_synopsis(existing, thesis_id=thesis_id)


@router.put("/synopsis", summary="Upsert thesis synopsis (create or replace)")
def upsert_synopsis(req: SynopsisCreateRequest, thesis_id: str = Query("")):
    """
    Idempotent upsert — creates the synopsis if it doesn't exist, or
    replaces it in full if it does. The frontend does not need to know
    which state currently applies.
    """
    data = req.model_dump()
    data["updated_at"] = datetime.utcnow().isoformat()
    return storage.write_synopsis(data, thesis_id=thesis_id)


# --- Chapters ---
# ADD:
@router.get("/list", summary="List all thesis namespaces")
def list_theses():
    return storage.list_theses()
 
 
@router.delete("/synopsis", summary="Delete thesis synopsis")
def delete_synopsis(thesis_id: str = Query("")):
    if not storage.delete_synopsis(thesis_id=thesis_id):
        raise HTTPException(status_code=404, detail="No synopsis found.")
    return {"deleted": True}
 
 
@router.delete("/namespace/{thesis_id}", summary="Delete an entire thesis namespace")
def delete_thesis_namespace(thesis_id: str):
    import shutil
    path = storage.DATA_DIR / "theses" / thesis_id
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Thesis '{thesis_id}' not found.")
    shutil.rmtree(path)
    return {"deleted": thesis_id}
 

@router.post("/chapters", summary="Add a chapter")
def create_chapter(req: ChapterCreateRequest, thesis_id: str = Query("")):
    chapter_id = f"chapter_{req.number:02d}"
    existing = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Chapter {req.number} already exists. Use PATCH to update."
        )
    data = {
        "chapter_id": chapter_id,
        "number": req.number,
        "title": req.title,
        "goal": req.goal,
        "subtopics": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    return storage.write_chapter(chapter_id, data, thesis_id=thesis_id)


@router.get("/chapters", summary="List all chapters")
def list_chapters(thesis_id: str = Query("")):
    return storage.list_chapters(thesis_id=thesis_id)


@router.get("/chapters/{chapter_id}", summary="Get a chapter with all its subtopics")
def get_chapter(chapter_id: str, thesis_id: str = Query("")):
    data = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")
    return data


@router.patch("/chapters/{chapter_id}", summary="Update chapter goal or title")
def update_chapter(chapter_id: str, updates: dict, thesis_id: str = Query("")):
    data = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")
    allowed = {"title", "goal"}
    for k, v in updates.items():
        if k in allowed:
            data[k] = v
    return storage.write_chapter(chapter_id, data, thesis_id=thesis_id)


@router.delete("/chapters/{chapter_id}", summary="Delete a chapter")
def delete_chapter(chapter_id: str, thesis_id: str = Query("")):
    if not storage.delete_chapter(chapter_id, thesis_id=thesis_id):
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")
    return {"deleted": chapter_id}


# --- Subtopics (nested under chapters) ---

@router.post("/chapters/{chapter_id}/subtopics", summary="Add a subtopic to a chapter")
def add_subtopic(chapter_id: str, req: SubtopicCreateRequest, thesis_id: str = Query("")):
    chapter = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    # Build subtopic_id from number: "1.3.2" -> "1_3_2"
    subtopic_id = req.number.replace(".", "_")

    # Check for duplicate
    existing_ids = [s["subtopic_id"] for s in chapter.get("subtopics", [])]
    if subtopic_id in existing_ids:
        raise HTTPException(
            status_code=409,
            detail=f"Subtopic {req.number} already exists in this chapter."
        )

    subtopic = {
        "subtopic_id": subtopic_id,
        "number": req.number,
        "title": req.title,
        "goal": req.goal,
        "position_in_argument": req.position_in_argument,
    }
    chapter.setdefault("subtopics", []).append(subtopic)
    storage.write_chapter(chapter_id, chapter, thesis_id=thesis_id)
    return subtopic


@router.patch(
    "/chapters/{chapter_id}/subtopics/{subtopic_id}",
    summary="Update a subtopic"
)
def update_subtopic(chapter_id: str, subtopic_id: str, req: SubtopicUpdateRequest, thesis_id: str = Query("")):
    chapter = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    subtopics = chapter.get("subtopics", [])
    target = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Subtopic '{subtopic_id}' not found.")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    target.update(updates)
    storage.write_chapter(chapter_id, chapter, thesis_id=thesis_id)
    return target


@router.delete(
    "/chapters/{chapter_id}/subtopics/{subtopic_id}",
    summary="Remove a subtopic"
)
def delete_subtopic(chapter_id: str, subtopic_id: str, thesis_id: str = Query("")):
    chapter = storage.read_chapter(chapter_id, thesis_id=thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    original = chapter.get("subtopics", [])
    filtered = [s for s in original if s["subtopic_id"] != subtopic_id]
    if len(filtered) == len(original):
        raise HTTPException(status_code=404, detail=f"Subtopic '{subtopic_id}' not found.")

    chapter["subtopics"] = filtered
    storage.write_chapter(chapter_id, chapter, thesis_id=thesis_id)
    return {"deleted": subtopic_id}


@router.get(
    "/chapters/{chapter_id}/subtopics/{subtopic_id}/suggested-sources",
    summary="Get sources whose index cards are tagged for this subtopic"
)
def get_suggested_sources(chapter_id: str, subtopic_id: str):
    """
    Returns all sources across all groups that have tagged this subtopic
    in their index card's relevant_subtopics field.
    Use this when building the source selection UI for a subtopic.
    """
    sources = storage.find_sources_for_subtopic(subtopic_id)
    return {
        "subtopic_id": subtopic_id,
        "suggested_sources": sources,
        "count": len(sources)
    }
