# ── spo_backend/services/storage.py — source group section changes ────────────

# ════════════════════════════════════════════
# CHANGE 1 — directory helpers (3 functions)
# ════════════════════════════════════════════
# FIND:
def _groups_dir() -> Path:
    return _ensure(DATA_DIR / "source_groups")

def _group_dir(group_id: str) -> Path:
    return _ensure(DATA_DIR / "source_groups" / group_id)

def _sources_dir(group_id: str) -> Path:
    return _ensure(DATA_DIR / "source_groups" / group_id / "sources")

# REPLACE WITH:
def _groups_dir(thesis_id: str = "") -> Path:
    root = DATA_DIR if not thesis_id else _ensure(DATA_DIR / "theses" / thesis_id)
    return _ensure(root / "source_groups")

def _group_dir(group_id: str, thesis_id: str = "") -> Path:
    return _ensure(_groups_dir(thesis_id) / group_id)

def _sources_dir(group_id: str, thesis_id: str = "") -> Path:
    return _ensure(_group_dir(group_id, thesis_id) / "sources")


# ════════════════════════════════════════════
# CHANGE 2 — cache state: add thesis tracker
# ════════════════════════════════════════════
# FIND:
_groups_cache: dict[str, dict] = {}
_groups_cache_loaded: bool = False

# REPLACE WITH:
_groups_cache: dict[str, dict] = {}
_groups_cache_loaded: bool = False
_groups_cache_thesis_id: str = ""   # tracks which thesis is currently in cache


# ════════════════════════════════════════════
# CHANGE 3 — internal cache helpers (4 functions)
# ════════════════════════════════════════════
# FIND:
def _load_group_from_disk(group_id: str) -> Optional[dict]:
    meta = _read(_group_dir(group_id) / "group_meta.json")
    if not meta:
        return None
    sources = _list_json(_sources_dir(group_id))
    meta["sources"] = sources
    meta["source_count"] = len(sources)
    meta["ready_count"] = sum(1 for s in sources if s.get("has_index_card"))
    return meta


def _ensure_groups_loaded() -> None:
    global _groups_cache_loaded
    if _groups_cache_loaded:
        return
    groups_dir = _groups_dir()
    if groups_dir.exists():
        for group_path in sorted(groups_dir.iterdir()):
            if group_path.is_dir():
                group_id = group_path.name
                entry = _load_group_from_disk(group_id)
                if entry is not None:
                    _groups_cache[group_id] = entry
    _groups_cache_loaded = True


def _evict_group(group_id: str) -> None:
    _groups_cache.pop(group_id, None)


def _get_group_entry(group_id: str) -> Optional[dict]:
    _ensure_groups_loaded()
    if group_id not in _groups_cache:
        entry = _load_group_from_disk(group_id)
        if entry is not None:
            _groups_cache[group_id] = entry
    return _groups_cache.get(group_id)

# REPLACE WITH:
def _load_group_from_disk(group_id: str, thesis_id: str = "") -> Optional[dict]:
    meta = _read(_group_dir(group_id, thesis_id) / "group_meta.json")
    if not meta:
        return None
    sources = _list_json(_sources_dir(group_id, thesis_id))
    meta["sources"] = sources
    meta["source_count"] = len(sources)
    meta["ready_count"] = sum(1 for s in sources if s.get("has_index_card"))
    return meta


def _ensure_groups_loaded(thesis_id: str = "") -> None:
    global _groups_cache_loaded, _groups_cache_thesis_id
    if _groups_cache_loaded and _groups_cache_thesis_id == thesis_id:
        return
    _groups_cache.clear()
    gdir = _groups_dir(thesis_id)
    if gdir.exists():
        for group_path in sorted(gdir.iterdir()):
            if group_path.is_dir():
                gid = group_path.name
                entry = _load_group_from_disk(gid, thesis_id)
                if entry is not None:
                    _groups_cache[gid] = entry
    _groups_cache_loaded = True
    _groups_cache_thesis_id = thesis_id


def _evict_group(group_id: str, thesis_id: str = "") -> None:
    if thesis_id == _groups_cache_thesis_id:
        _groups_cache.pop(group_id, None)
    else:
        # Writing to a different thesis than what's cached — full invalidation
        global _groups_cache_loaded
        _groups_cache.clear()
        _groups_cache_loaded = False


def _get_group_entry(group_id: str, thesis_id: str = "") -> Optional[dict]:
    _ensure_groups_loaded(thesis_id)
    if group_id not in _groups_cache:
        entry = _load_group_from_disk(group_id, thesis_id)
        if entry is not None:
            _groups_cache[group_id] = entry
    return _groups_cache.get(group_id)


# ════════════════════════════════════════════
# CHANGE 4 — all public source CRUD functions + get_entire_library_data
# Add thesis_id="" param and pass through to every internal call.
# ════════════════════════════════════════════
# FIND:
def list_source_groups() -> list[dict]:
    _ensure_groups_loaded()
    result = []
    for entry in sorted(_groups_cache.values(), key=lambda g: g.get("group_id", "")):
        meta = {k: v for k, v in entry.items() if k != "sources"}
        meta["source_count"] = entry.get("source_count", 0)
        meta["ready_count"] = entry.get("ready_count", 0)
        result.append(meta)
    return result


def read_source_group(group_id: str) -> Optional[dict]:
    """Return a single group with sources embedded. Zero disk reads when warm."""
    return _get_group_entry(group_id)


def write_source_group(group_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    sources = data.pop("sources", [])
    _write(_group_dir(group_id) / "group_meta.json", data)
    data["sources"] = sources
    _evict_group(group_id)
    return data


def delete_source_group(group_id: str) -> bool:
    group_path = _group_dir(group_id)
    if group_path.exists():
        shutil.rmtree(group_path)
        _evict_group(group_id)
        return True
    return False


def list_sources(group_id: str) -> list[dict]:
    """Zero disk reads when cache is warm."""
    entry = _get_group_entry(group_id)
    if entry is not None:
        return entry.get("sources", [])
    return _list_json(_sources_dir(group_id))


def read_source(group_id: str, source_id: str) -> Optional[dict]:
    entry = _get_group_entry(group_id)
    if entry is not None:
        for s in entry.get("sources", []):
            if s.get("source_id") == source_id:
                return s
    return _read(_sources_dir(group_id) / f"{source_id}.json")


def write_source(group_id: str, source_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_sources_dir(group_id) / f"{source_id}.json", data)
    _evict_group(group_id)
    return data


def delete_source(group_id: str, source_id: str) -> bool:
    path = _sources_dir(group_id) / f"{source_id}.json"
    if path.exists():
        path.unlink()
        _evict_group(group_id)
        return True
    return False


def write_index_card(group_id: str, source_id: str, card_data: dict) -> Optional[dict]:
    source = read_source(group_id, source_id)
    if not source:
        return None
    card_data["updated_at"] = datetime.utcnow().isoformat()
    if "created_at" not in card_data:
        card_data["created_at"] = datetime.utcnow().isoformat()
    source["index_card"] = card_data
    source["has_index_card"] = True
    write_source(group_id, source_id, source)
    return card_data


def delete_index_card(group_id: str, source_id: str) -> bool:
    source = read_source(group_id, source_id)
    if not source:
        return False
    source["index_card"] = None
    source["has_index_card"] = False
    write_source(group_id, source_id, source)
    return True

# REPLACE WITH:
def list_source_groups(thesis_id: str = "") -> list[dict]:
    _ensure_groups_loaded(thesis_id)
    result = []
    for entry in sorted(_groups_cache.values(), key=lambda g: g.get("group_id", "")):
        meta = {k: v for k, v in entry.items() if k != "sources"}
        meta["source_count"] = entry.get("source_count", 0)
        meta["ready_count"] = entry.get("ready_count", 0)
        result.append(meta)
    return result


def read_source_group(group_id: str, thesis_id: str = "") -> Optional[dict]:
    return _get_group_entry(group_id, thesis_id)


def write_source_group(group_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    sources = data.pop("sources", [])
    _write(_group_dir(group_id, thesis_id) / "group_meta.json", data)
    data["sources"] = sources
    _evict_group(group_id, thesis_id)
    return data


def delete_source_group(group_id: str, thesis_id: str = "") -> bool:
    group_path = _group_dir(group_id, thesis_id)
    if group_path.exists():
        shutil.rmtree(group_path)
        _evict_group(group_id, thesis_id)
        return True
    return False


def list_sources(group_id: str, thesis_id: str = "") -> list[dict]:
    entry = _get_group_entry(group_id, thesis_id)
    if entry is not None:
        return entry.get("sources", [])
    return _list_json(_sources_dir(group_id, thesis_id))


def read_source(group_id: str, source_id: str, thesis_id: str = "") -> Optional[dict]:
    entry = _get_group_entry(group_id, thesis_id)
    if entry is not None:
        for s in entry.get("sources", []):
            if s.get("source_id") == source_id:
                return s
    return _read(_sources_dir(group_id, thesis_id) / f"{source_id}.json")


def write_source(group_id: str, source_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_sources_dir(group_id, thesis_id) / f"{source_id}.json", data)
    _evict_group(group_id, thesis_id)
    return data


def delete_source(group_id: str, source_id: str, thesis_id: str = "") -> bool:
    path = _sources_dir(group_id, thesis_id) / f"{source_id}.json"
    if path.exists():
        path.unlink()
        _evict_group(group_id, thesis_id)
        return True
    return False


def write_index_card(group_id: str, source_id: str, card_data: dict,
                     thesis_id: str = "") -> Optional[dict]:
    source = read_source(group_id, source_id, thesis_id)
    if not source:
        return None
    card_data["updated_at"] = datetime.utcnow().isoformat()
    if "created_at" not in card_data:
        card_data["created_at"] = datetime.utcnow().isoformat()
    source["index_card"] = card_data
    source["has_index_card"] = True
    write_source(group_id, source_id, source, thesis_id)
    return card_data


def delete_index_card(group_id: str, source_id: str, thesis_id: str = "") -> bool:
    source = read_source(group_id, source_id, thesis_id)
    if not source:
        return False
    source["index_card"] = None
    source["has_index_card"] = False
    write_source(group_id, source_id, source, thesis_id)
    return True


# Also update get_entire_library_data:
# FIND:
def get_entire_library_data() -> dict:
    _ensure_groups_loaded()
    _ensure_notes_loaded("source_group")
    _ensure_notes_loaded("source")
    groups_data = sorted(_groups_cache.values(), key=lambda g: g.get("group_id", ""))
    notes_data = {
        "source_group": _notes_cache.get("source_group", {}),
        "source":       _notes_cache.get("source", {}),
    }
    return {"groups": groups_data, "notes": notes_data}

# REPLACE WITH:
def get_entire_library_data(thesis_id: str = "") -> dict:
    _ensure_groups_loaded(thesis_id)
    _ensure_notes_loaded("source_group")
    _ensure_notes_loaded("source")
    groups_data = sorted(_groups_cache.values(), key=lambda g: g.get("group_id", ""))
    notes_data = {
        "source_group": _notes_cache.get("source_group", {}),
        "source":       _notes_cache.get("source", {}),
    }
    return {"groups": groups_data, "notes": notes_data}
