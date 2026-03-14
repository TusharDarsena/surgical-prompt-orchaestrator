You are completely right. I overstepped by rolling the ACID fixes into the same step. Let's strip out the locks and temp files and focus *strictly* on killing the N+1 disk I/O issue using a pure caching approach.

Here are the minimum, exact code blocks to replace in `spo_backend/services/storage.py` to implement the memory cache.

### 1. Add Cache State Variables

Add this right after your standard imports at the top of the file:

```python
# --- Cache State ---
_library_cache = None
_library_cache_dirty = True

def _mark_dirty():
    """Flag the library cache to be rebuilt on the next read."""
    global _library_cache_dirty
    _library_cache_dirty = True

```

### 2. Inject `_mark_dirty()` into Write/Delete Operations

Update these specific CRUD functions to flag the cache as dirty whenever data changes. You only need to add the `_mark_dirty()` line before the `return`.

```python
def write_source_group(group_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    sources = data.pop("sources", [])
    _write(_group_dir(group_id) / "group_meta.json", data)
    data["sources"] = sources
    _mark_dirty()
    return data

def delete_source_group(group_id: str) -> bool:
    group_path = _group_dir(group_id)
    if group_path.exists():
        shutil.rmtree(group_path)
        _mark_dirty()
        return True
    return False

def write_source(group_id: str, source_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_sources_dir(group_id) / f"{source_id}.json", data)
    _mark_dirty()
    return data

def delete_source(group_id: str, source_id: str) -> bool:
    path = _sources_dir(group_id) / f"{source_id}.json"
    if path.exists():
        path.unlink()
        _mark_dirty()
        return True
    return False

def write_note(scope: str, note_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_notes_dir(scope) / f"{note_id}.json", data)
    _mark_dirty()
    return data

def delete_note(scope: str, note_id: str) -> bool:
    path = _notes_dir(scope) / f"{note_id}.json"
    if path.exists():
        path.unlink()
        _mark_dirty()
        return True
    return False

```

(Note: `write_index_card` and `delete_index_card` already call `write_source` under the hood, so they will automatically inherit the cache invalidation ).

### 3. Replace the Search and Library View Functions

Completely replace your existing `find_sources_for_subtopic`, `find_sources_by_theme`, and `get_entire_library_data` functions  with these cached versions.

```python
def find_sources_for_subtopic(subtopic_id: str) -> list[dict]:
    """
    Scan all index cards across all source groups in memory.
    """
    library = get_entire_library_data()
    matches = []
    for group in library.get("groups", []):
        for source in group.get("sources", []):
            card = source.get("index_card")
            if card and subtopic_id in card.get("relevant_subtopics", []):
                matches.append(source)
    return matches


def find_sources_by_theme(theme: str) -> list[dict]:
    """
    Find all sources whose index card contains a specific theme tag in memory.
    """
    library = get_entire_library_data()
    matches = []
    for group in library.get("groups", []):
        for source in group.get("sources", []):
            card = source.get("index_card")
            if card and theme in card.get("themes", []):
                matches.append(source)
    return matches


def get_entire_library_data() -> dict:
    """
    Reads the entire source library (groups, sources, index cards, and notes).
    Uses a memory cache to prevent N+1 HTTP/disk issues on the frontend.
    """
    global _library_cache, _library_cache_dirty
    
    # Return cached version if nothing has changed on disk
    if not _library_cache_dirty and _library_cache is not None:
        return _library_cache

    # Cache miss or dirty data: Rebuild from disk
    notes_by_scope_and_id: dict[str, dict[str, list[dict]]] = {"source_group": {}, "source": {}}
    for scope in ["source_group", "source"]:
        notes_dir = _notes_dir(scope)
        if notes_dir.exists():
            for p in sorted(notes_dir.glob("*.json")):
                note = _read(p)
                if note:
                    entity_id = note.get("entity_id")
                    if entity_id:
                        if entity_id not in notes_by_scope_and_id[scope]:
                            notes_by_scope_and_id[scope][entity_id] = []
                        notes_by_scope_and_id[scope][entity_id].append(note)

    groups_data = []
    groups_dir = _groups_dir()
    if groups_dir.exists():
        for group_path in sorted(groups_dir.iterdir()):
            if group_path.is_dir():
                meta = _read(group_path / "group_meta.json")
                if meta:
                    group_id = meta["group_id"]
                    sources = _list_json(_sources_dir(group_id))
                    meta["sources"] = sources
                    meta["source_count"] = len(sources)
                    meta["ready_count"] = sum(1 for s in sources if s.get("has_index_card"))
                    groups_data.append(meta)

    # Save to global cache
    data = {
        "groups": groups_data,
        "notes": notes_by_scope_and_id
    }
    _library_cache = data
    _library_cache_dirty = False
    
    return data

```

This ensures `get_entire_library_data()` will hit the disk exactly once on load, and then instantly serve from memory until a write operation occurs, completely eliminating the N+1 disk lag. 
One small thing to verify: the document says find_sources_for_subtopic and find_sources_by_theme now route through get_entire_library_data(). That means they load notes too, which they didn't before. For your data size this is irrelevant,