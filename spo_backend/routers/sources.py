"""
Source Library Router
---------------------
Full CRUD for SourceGroups, Sources, and IndexCards.
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime

from models.sources import (
    SourceGroupCreateRequest, SourceGroupUpdateRequest,
    SourceCreateRequest, SourceUpdateRequest,
    IndexCardCreateRequest, IndexCardUpdateRequest,
)
from services import storage

router = APIRouter(prefix="/sources", tags=["Source Library"])


# --- Source Groups ---

@router.post("/groups", summary="Create a new source group (a complete work)")
def create_group(req: SourceGroupCreateRequest):
    """
    Create a SourceGroup for a complete work (thesis, book, journal issue).
    After creating the group, add individual chapter/article Sources to it.
    """
    import uuid
    group_id = str(uuid.uuid4())[:8]
    data = req.model_dump()
    data["group_id"] = group_id
    data["sources"] = []
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = datetime.utcnow().isoformat()
    storage.write_source_group(group_id, data)
    return storage.read_source_group(group_id)


@router.get("/groups", summary="List all source groups")
def list_groups():
    groups = storage.list_source_groups()
    # Attach source counts without loading all source data
    result = []
    for g in groups:
        sources = storage.list_sources(g["group_id"])
        g["source_count"] = len(sources)
        g["ready_count"] = sum(1 for s in sources if s.get("has_index_card"))
        result.append(g)
    return result

@router.get("/library-view", summary="Get entire source library (groups, sources, notes) in one pass")
def get_library_view():
    """
    Returns the full nested structure of the source library to avoid
    N+1 queries from the frontend on initial page load.
    """
    return storage.get_entire_library_data()


@router.get("/groups/{group_id}", summary="Get a source group with all its sources")
def get_group(group_id: str):
    data = storage.read_source_group(group_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")
    return data


@router.patch("/groups/{group_id}", summary="Update source group metadata")
def update_group(group_id: str, req: SourceGroupUpdateRequest):
    data = storage.read_source_group(group_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    data.update(updates)
    return storage.write_source_group(group_id, data)


@router.delete("/groups/{group_id}", summary="Delete a source group and all its sources")
def delete_group(group_id: str):
    if not storage.delete_source_group(group_id):
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")
    return {"deleted": group_id}


# --- Sources ---

@router.post("/groups/{group_id}/sources", summary="Add a source document to a group")
def create_source(group_id: str, req: SourceCreateRequest):
    """
    Add one PDF chapter or article as a Source within a SourceGroup.
    The Source starts without an index card — fill the index card after reading.
    """
    group = storage.read_source_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")

    import uuid
    source_id = str(uuid.uuid4())[:8]
    data = req.model_dump()
    data["source_id"] = source_id
    data["group_id"] = group_id
    data["index_card"] = None
    data["has_index_card"] = False
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = datetime.utcnow().isoformat()
    return storage.write_source(group_id, source_id, data)


@router.get("/groups/{group_id}/sources", summary="List all sources in a group")
def list_sources(group_id: str):
    group = storage.read_source_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail=f"Group '{group_id}' not found.")
    return storage.list_sources(group_id)


@router.get("/groups/{group_id}/sources/{source_id}", summary="Get a source with its index card")
def get_source(group_id: str, source_id: str):
    data = storage.read_source(group_id, source_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    return data


@router.patch("/groups/{group_id}/sources/{source_id}", summary="Update source metadata")
def update_source(group_id: str, source_id: str, req: SourceUpdateRequest):
    data = storage.read_source(group_id, source_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    data.update(updates)
    return storage.write_source(group_id, source_id, data)


@router.delete("/groups/{group_id}/sources/{source_id}", summary="Delete a source")
def delete_source(group_id: str, source_id: str):
    if not storage.delete_source(group_id, source_id):
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    return {"deleted": source_id}


# --- Index Cards ---

@router.post(
    "/groups/{group_id}/sources/{source_id}/index-card",
    summary="Create index card for a source"
)
def create_index_card(group_id: str, source_id: str, req: IndexCardCreateRequest):
    """
    Write the index card for a source after reading it.
    This is the most valuable step — take time to write specific key_claims
    and tag relevant_subtopics accurately.
    """
    source = storage.read_source(group_id, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    if source.get("has_index_card"):
        raise HTTPException(
            status_code=409,
            detail="Index card already exists. Use PATCH to update it."
        )
    card_data = req.model_dump()
    result = storage.write_index_card(group_id, source_id, card_data)
    return result


@router.get(
    "/groups/{group_id}/sources/{source_id}/index-card",
    summary="Get index card for a source"
)
def get_index_card(group_id: str, source_id: str):
    source = storage.read_source(group_id, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    if not source.get("has_index_card"):
        raise HTTPException(
            status_code=404,
            detail="No index card yet. Read the source and create one."
        )
    return source["index_card"]


@router.patch(
    "/groups/{group_id}/sources/{source_id}/index-card",
    summary="Update index card (partial update)"
)
def update_index_card(group_id: str, source_id: str, req: IndexCardUpdateRequest):
    source = storage.read_source(group_id, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    if not source.get("has_index_card"):
        raise HTTPException(status_code=404, detail="No index card to update. Create one first.")
    existing_card = source["index_card"]
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    existing_card.update(updates)
    result = storage.write_index_card(group_id, source_id, existing_card)
    return result


@router.delete(
    "/groups/{group_id}/sources/{source_id}/index-card",
    summary="Delete index card (source becomes un-ready)"
)
def delete_index_card(group_id: str, source_id: str):
    source = storage.read_source(group_id, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{source_id}' not found.")
    storage.delete_index_card(group_id, source_id)
    return {"deleted": "index_card", "source_id": source_id}


# --- Discovery ---

@router.get("/search/by-theme/{theme}", summary="Find all sources with a given theme tag")
def search_by_theme(theme: str):
    sources = storage.find_sources_by_theme(theme)
    return {"theme": theme, "sources": sources, "count": len(sources)}


@router.get("/ready", summary="List all sources that have index cards (ready for prompts)")
def list_ready_sources():
    """Returns all sources across all groups that are ready for prompt injection."""
    groups = storage.list_source_groups()
    ready = []
    for g in groups:
        for source in storage.list_sources(g["group_id"]):
            if source.get("has_index_card"):
                source["group_title"] = g.get("title", "")
                ready.append(source)
    return {"ready_sources": ready, "count": len(ready)}
