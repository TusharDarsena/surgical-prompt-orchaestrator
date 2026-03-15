# ══════════════════════════════════════════════════════════════════
# spo_backend/routers/sources.py
# ══════════════════════════════════════════════════════════════════
# CHANGE 1 — import line
# FIND:
from fastapi import APIRouter, HTTPException
# REPLACE WITH:
from fastapi import APIRouter, HTTPException, Query

# CHANGE 2 — add thesis_id param to every endpoint.
# Pattern: add `thesis_id: str = Query("")` as last param,
# pass `thesis_id=thesis_id` to every storage call in that function.
# All 13 endpoints follow the same pattern. Key examples:

# FIND:
def get_library_view():
    return storage.get_entire_library_data()

# REPLACE WITH:
def get_library_view(thesis_id: str = Query("")):
    return storage.get_entire_library_data(thesis_id=thesis_id)


# FIND:
def create_group(req: SourceGroupCreateRequest):
    import uuid
    group_id = str(uuid.uuid4())[:8]
    data = req.model_dump()
    data["group_id"] = group_id
    data["sources"] = []
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = datetime.utcnow().isoformat()
    storage.write_source_group(group_id, data)
    return storage.read_source_group(group_id)

# REPLACE WITH:
def create_group(req: SourceGroupCreateRequest, thesis_id: str = Query("")):
    import uuid
    group_id = str(uuid.uuid4())[:8]
    data = req.model_dump()
    data["group_id"] = group_id
    data["sources"] = []
    data["created_at"] = datetime.utcnow().isoformat()
    data["updated_at"] = datetime.utcnow().isoformat()
    storage.write_source_group(group_id, data, thesis_id=thesis_id)
    return storage.read_source_group(group_id, thesis_id=thesis_id)

# Apply same pattern (add thesis_id param + pass to storage) to:
#   list_groups, get_group, update_group, delete_group,
#   create_source, list_sources, get_source, update_source, delete_source,
#   create_index_card, update_index_card, delete_index_card, get_index_card


# ══════════════════════════════════════════════════════════════════
# spo_backend/routers/importer.py
# ══════════════════════════════════════════════════════════════════
# FIND:
@router.post("/source", summary="Import source.json — creates group + all sources + index cards in one upload")
def import_source(data: dict = Body(...)):
    result, error = do_auto_import(data)

# REPLACE WITH:
@router.post("/source", summary="Import source.json — creates group + all sources + index cards in one upload")
def import_source(data: dict = Body(...), thesis_id: str = Query("")):
    result, error = do_auto_import(data, thesis_id=thesis_id)


# ══════════════════════════════════════════════════════════════════
# spo_backend/services/source_importer.py
# ══════════════════════════════════════════════════════════════════
# FIND:
def do_auto_import(data: dict) -> tuple[dict | None, str | None]:

# REPLACE WITH:
def do_auto_import(data: dict, thesis_id: str = "") -> tuple[dict | None, str | None]:

# Then inside do_auto_import, find:
    storage.write_source_group(group_id, group_record)
# REPLACE WITH:
    storage.write_source_group(group_id, group_record, thesis_id=thesis_id)

# And find:
        storage.write_source(group_id, source_id, source_record)
# REPLACE WITH:
        storage.write_source(group_id, source_id, source_record, thesis_id=thesis_id)
