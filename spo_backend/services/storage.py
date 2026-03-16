"""
File Storage Service
--------------------
All persistence is handled here. No database — just JSON files on disk.
This is intentional for a personal project: zero infrastructure,
portable, human-readable, easy to back up.

Directory layout (under SPO_DATA_DIR, default: ~/spo_data):

  spo_data/
    thesis_context/
      synopsis.json
      chapters/
        chapter_01.json
        chapter_02.json
    source_groups/
      {group_id}/
        group_meta.json
        sources/
          {source_id}.json
    consistency_chain/
      {chapter_id}/
        {subtopic_id}.json

Cache design
------------
Three independent caches — each tracks only what it owns:

  _groups_cache : dict[group_id, {meta + sources[]}]
      Populated lazily on first access, invalidated per-group on write/delete.
      Cross-group scans (find_sources_*) use the warmed cache directly.

  _notes_cache  : dict[scope, dict[entity_id, list[note]]]
      Completely separate from groups. Notes reads never touch source_groups/,
      source reads never rebuild notes.

  _drive_scan_cache : dict | None
      drive_scan_result.json is read once and held. Invalidated on write_misc
      for that specific key. resolve_source_files never hits disk in a loop.

Fine-grained invalidation means a single source write only evicts that group's
cache entry, not the whole library. Notes writes only evict the notes cache.

Multi-process note
------------------
These caches are per-process. In a multi-worker server (gunicorn, uvicorn)
each worker maintains its own copy. For a personal/single-user project this
is acceptable; the cost of a stale read is one outdated response before the
next write refreshes that worker's entry. If you later need cross-process
consistency, replace the dicts below with a shared memory backend (e.g. Redis)
without changing any of the public function signatures.
"""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Base path
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("SPO_DATA_DIR", Path.home() / "spo_data"))


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _thesis_dir(thesis_id: str = "") -> Path:
    root = DATA_DIR if not thesis_id else _ensure(DATA_DIR / "theses" / thesis_id)
    return _ensure(root / "thesis_context")
 
def _chapters_dir(thesis_id: str = "") -> Path:
    root = DATA_DIR if not thesis_id else _ensure(DATA_DIR / "theses" / thesis_id)
    return _ensure(root / "thesis_context" / "chapters")

def _groups_dir(thesis_id: str = "") -> Path:
    root = DATA_DIR if not thesis_id else _ensure(DATA_DIR / "theses" / thesis_id)
    return _ensure(root / "source_groups")

def _group_dir(group_id: str, thesis_id: str = "") -> Path:
    return _ensure(_groups_dir(thesis_id) / group_id)

def _sources_dir(group_id: str, thesis_id: str = "") -> Path:
    return _ensure(_group_dir(group_id, thesis_id) / "sources")

def _chain_dir(chapter_id: str) -> Path:
    return _ensure(DATA_DIR / "consistency_chain" / chapter_id)

def _notes_dir(scope: str, thesis_id: str = "") -> Path:
    root = DATA_DIR if not thesis_id else _ensure(DATA_DIR / "theses" / thesis_id)
    return _ensure(root / "notes" / scope)

def _misc_dir() -> Path:
    return _ensure(DATA_DIR / "misc")

def _drafts_dir(chapter_id: str) -> Path:
    return _ensure(DATA_DIR / "sections" / chapter_id)

def _nlm_state_dir(chapter_id: str) -> Path:
    return _ensure(DATA_DIR / "sections" / chapter_id)


# ---------------------------------------------------------------------------
# Generic read / write
# ---------------------------------------------------------------------------

def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    tmp.replace(path)          # atomic on POSIX; best-effort on Windows


def _list_json(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


# ---------------------------------------------------------------------------
# Cache 1 — groups (meta + embedded sources, keyed by group_id)
#
# Structure:
#   _groups_cache = {
#       group_id: {
#           **group_meta,
#           "sources": [...],
#           "source_count": int,
#           "ready_count": int,
#       },
#       ...
#   }
#   _groups_cache_loaded = False   # True once we've done the initial full scan
#
# Invariant: if _groups_cache_loaded is True, _groups_cache contains every
# group that exists on disk. Individual entries are evicted on write/delete
# and re-read from disk on next access; a new full scan is never needed again
# because we track individual entries.
# ---------------------------------------------------------------------------

_groups_cache: dict[str, dict] = {}
_groups_cache_loaded: bool = False
_groups_cache_thesis_id: str = ""   # tracks which thesis is currently in cache


def _load_group_from_disk(group_id: str, thesis_id: str = "") -> Optional[dict]:
    """Read one group (meta + sources) from disk and return the assembled entry."""
    meta = _read(_group_dir(group_id, thesis_id) / "group_meta.json")
    if not meta:
        return None
    sources = _list_json(_sources_dir(group_id, thesis_id))
    meta["sources"] = sources
    meta["source_count"] = len(sources)
    meta["ready_count"] = sum(1 for s in sources if s.get("has_index_card"))
    return meta


def _ensure_groups_loaded(thesis_id: str = "") -> None:
    """
    Populate _groups_cache with every group on disk — exactly once.
    After this call, individual entries are kept current via fine-grained
    eviction; no second full scan ever happens during the process lifetime.
    """
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
    """Remove one group entry from cache so it is re-read on next access."""
    if thesis_id == _groups_cache_thesis_id:
        _groups_cache.pop(group_id, None)
    else:
        # Writing to a different thesis than what's cached — full invalidation
        global _groups_cache_loaded
        _groups_cache.clear()
        _groups_cache_loaded = False


def _get_group_entry(group_id: str, thesis_id: str = "") -> Optional[dict]:
    """Return the cached entry for one group, loading from disk if needed."""
    _ensure_groups_loaded(thesis_id)
    if group_id not in _groups_cache:
        entry = _load_group_from_disk(group_id, thesis_id)
        if entry is not None:
            _groups_cache[group_id] = entry
    return _groups_cache.get(group_id)


# ---------------------------------------------------------------------------
# Cache 2 — notes (keyed by scope → entity_id → list[note])
#
# Completely independent of the groups cache. A notes read never touches
# source_groups/, and a source write never evicts notes.
# ---------------------------------------------------------------------------

_notes_cache: dict[str, dict[str, list[dict]]] = {}
_notes_cache_loaded: set[str] = set()
_notes_cache_thesis_id: str = ""

def _ensure_notes_loaded(scope: str, thesis_id: str = "") -> None:
    global _notes_cache_loaded, _notes_cache_thesis_id
    
    # If switching to a new thesis, clear the notes cache
    if _notes_cache_thesis_id != thesis_id:
        _notes_cache.clear()
        _notes_cache_loaded.clear()
        _notes_cache_thesis_id = thesis_id

    if scope in _notes_cache_loaded:
        return
        
    notes_dir = _notes_dir(scope, thesis_id)
    scope_map: dict[str, list[dict]] = {}
    if notes_dir.exists():
        for p in sorted(notes_dir.glob("*.json")):
            note = _read(p)
            if note:
                entity_id = note.get("entity_id")
                if entity_id:
                    scope_map.setdefault(entity_id, []).append(note)
    _notes_cache[scope] = scope_map
    _notes_cache_loaded.add(scope)

def _evict_note(scope: str, entity_id: str, note_id: str, thesis_id: str = "") -> None:
    if thesis_id != _notes_cache_thesis_id:
        return
    if scope not in _notes_cache:
        return
    entity_notes = _notes_cache[scope].get(entity_id, [])
    _notes_cache[scope][entity_id] = [
        n for n in entity_notes if n.get("note_id") != note_id
    ]

def _upsert_note_in_cache(scope: str, entity_id: str, note: dict, thesis_id: str = "") -> None:
    if thesis_id != _notes_cache_thesis_id:
        return
    if scope not in _notes_cache_loaded:
        return
    note_id = note.get("note_id")
    entity_notes = _notes_cache[scope].setdefault(entity_id, [])
    _notes_cache[scope][entity_id] = [
        n for n in entity_notes if n.get("note_id") != note_id
    ] + [note]

# ---------------------------------------------------------------------------
# Cache 3 — drive scan result (single JSON blob, invalidated by key)
# ---------------------------------------------------------------------------

_drive_scan_cache: Optional[dict] = None
_drive_scan_loaded: bool = False


def _get_drive_scan() -> dict:
    global _drive_scan_cache, _drive_scan_loaded
    if not _drive_scan_loaded:
        _drive_scan_cache = _read(_misc_dir() / "drive_scan_result.json") or {}
        _drive_scan_loaded = True
    return _drive_scan_cache or {}


def _invalidate_drive_scan() -> None:
    global _drive_scan_cache, _drive_scan_loaded
    _drive_scan_cache = None
    _drive_scan_loaded = False


# ---------------------------------------------------------------------------
# Synopsis
# ---------------------------------------------------------------------------

def read_synopsis(thesis_id: str = "") -> Optional[dict]:
    return _read(_thesis_dir(thesis_id) / "synopsis.json")
 
 
def write_synopsis(data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_thesis_dir(thesis_id) / "synopsis.json", data)
    return data
def delete_synopsis(thesis_id: str = "") -> bool:
    path = _thesis_dir(thesis_id) / "synopsis.json"
    if path.exists():
        path.unlink()
        return True
    return False
 
 
def list_theses() -> list[dict]:
    """Return all thesis namespaces that have a synopsis.json on disk."""
    results = []
    syn = _read(_thesis_dir("") / "synopsis.json")
    if syn:
        results.append({
            "thesis_id": "",
            "title": syn.get("title", ""),
            "author": syn.get("researcher") or syn.get("author", ""),
        })
    theses_root = DATA_DIR / "theses"
    if theses_root.exists():
        for d in sorted(theses_root.iterdir()):
            if d.is_dir():
                syn = _read(_thesis_dir(d.name) / "synopsis.json")
                if syn:
                    results.append({
                        "thesis_id": d.name,
                        "title": syn.get("title", ""),
                        "author": syn.get("researcher") or syn.get("author", ""),
                    })
    return results
 
# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------

def list_chapters(thesis_id: str = "") -> list[dict]:
    return _list_json(_chapters_dir(thesis_id))
 
 
def read_chapter(chapter_id: str, thesis_id: str = "") -> Optional[dict]:
    return _read(_chapters_dir(thesis_id) / f"{chapter_id}.json")
 
 
def write_chapter(chapter_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_chapters_dir(thesis_id) / f"{chapter_id}.json", data)
    return data
 
 
def delete_chapter(chapter_id: str, thesis_id: str = "") -> bool:
    path = _chapters_dir(thesis_id) / f"{chapter_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False

# ---------------------------------------------------------------------------
# Source Groups
# ---------------------------------------------------------------------------

def list_source_groups(thesis_id: str = "") -> list[dict]:
    """
    Return group meta + counts for all groups.
    Sources list is stripped — callers that need sources use read_source_group().
    Zero disk reads when cache is warm.
    """
    _ensure_groups_loaded(thesis_id)
    result = []
    for entry in sorted(_groups_cache.values(), key=lambda g: g.get("group_id", "")):
        meta = {k: v for k, v in entry.items() if k != "sources"}
        meta["source_count"] = entry.get("source_count", 0)
        meta["ready_count"] = entry.get("ready_count", 0)
        result.append(meta)
    return result


def read_source_group(group_id: str, thesis_id: str = "") -> Optional[dict]:
    """Return a single group with sources embedded. Zero disk reads when warm."""
    return _get_group_entry(group_id, thesis_id)


def write_source_group(group_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    sources = data.pop("sources", [])
    _write(_group_dir(group_id, thesis_id) / "group_meta.json", data)
    data["sources"] = sources
    # Evict this group so the next read gets a fresh assembled entry.
    # Other groups are unaffected.
    _evict_group(group_id, thesis_id)
    return data


def delete_source_group(group_id: str, thesis_id: str = "") -> bool:
    group_path = _group_dir(group_id, thesis_id)
    if group_path.exists():
        shutil.rmtree(group_path)
        _evict_group(group_id, thesis_id)
        return True
    return False


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def list_sources(group_id: str, thesis_id: str = "") -> list[dict]:
    """Zero disk reads when cache is warm."""
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
    # Cache miss (group not found) — fall back to direct disk read
    return _read(_sources_dir(group_id, thesis_id) / f"{source_id}.json")


def write_source(group_id: str, source_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_sources_dir(group_id, thesis_id) / f"{source_id}.json", data)
    # Evict only the owning group — every other group's cache is untouched
    _evict_group(group_id, thesis_id)
    return data


def delete_source(group_id: str, source_id: str, thesis_id: str = "") -> bool:
    path = _sources_dir(group_id, thesis_id) / f"{source_id}.json"
    if path.exists():
        path.unlink()
        _evict_group(group_id, thesis_id)
        return True
    return False


# ---------------------------------------------------------------------------
# Index Cards  (stored within the source file)
# ---------------------------------------------------------------------------

def write_index_card(group_id: str, source_id: str, card_data: dict, thesis_id: str = "") -> Optional[dict]:
    source = read_source(group_id, source_id, thesis_id)
    if not source:
        return None
    card_data["updated_at"] = datetime.utcnow().isoformat()
    if "created_at" not in card_data:
        card_data["created_at"] = datetime.utcnow().isoformat()
    source["index_card"] = card_data
    source["has_index_card"] = True
    write_source(group_id, source_id, source, thesis_id)   # evicts group cache
    return card_data


def delete_index_card(group_id: str, source_id: str, thesis_id: str = "") -> bool:
    source = read_source(group_id, source_id, thesis_id)
    if not source:
        return False
    source["index_card"] = None
    source["has_index_card"] = False
    write_source(group_id, source_id, source, thesis_id)   # evicts group cache
    return True


# ---------------------------------------------------------------------------
# Consistency Chain
# ---------------------------------------------------------------------------

def list_section_summaries(chapter_id: str) -> list[dict]:
    return _list_json(_chain_dir(chapter_id))


def read_section_summary(chapter_id: str, subtopic_id: str) -> Optional[dict]:
    return _read(_chain_dir(chapter_id) / f"{subtopic_id}.json")


def write_section_summary(chapter_id: str, subtopic_id: str, data: dict) -> dict:
    data["chapter_id"] = chapter_id
    data["subtopic_id"] = subtopic_id
    data["created_at"] = datetime.utcnow().isoformat()
    _write(_chain_dir(chapter_id) / f"{subtopic_id}.json", data)
    return data


def delete_section_summary(chapter_id: str, subtopic_id: str) -> bool:
    path = _chain_dir(chapter_id) / f"{subtopic_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Cross-cutting: find sources by subtopic / theme
#
# Both functions use the warmed groups cache — zero disk reads after the
# first call to any groups accessor in this process.
# ---------------------------------------------------------------------------

def find_sources_for_subtopic(subtopic_id: str, thesis_id: str = "") -> list[dict]:
    """
    Scan all index cards across all groups for relevant_subtopics membership.
    Uses in-memory cache — O(total_sources) with zero disk I/O when warm.
    """
    _ensure_groups_loaded(thesis_id)
    matches = []
    for entry in _groups_cache.values():
        for source in entry.get("sources", []):
            card = source.get("index_card")
            if card and subtopic_id in card.get("relevant_subtopics", []):
                matches.append(source)
    return matches


def find_sources_by_theme(theme: str, thesis_id: str = "") -> list[dict]:
    """
    Scan all index cards across all groups for a specific theme tag.
    Uses in-memory cache — O(total_sources) with zero disk I/O when warm.
    """
    _ensure_groups_loaded(thesis_id)
    matches = []
    for entry in _groups_cache.values():
        for source in entry.get("sources", []):
            card = source.get("index_card")
            if card and theme in card.get("themes", []):
                matches.append(source)
    return matches


# ---------------------------------------------------------------------------
# Library Bulk View
#
# Composes from the two independent caches. Notes and groups are loaded
# separately; loading one never triggers a read of the other.
# ---------------------------------------------------------------------------

def get_entire_library_data(thesis_id: str = "") -> dict:
    """
    Return the full library snapshot used by the frontend.

    Structure:
    {
        "groups": [{...group_meta, "sources": [...]}],
        "notes": {
            "source_group": {"group_id": [note, ...]},
            "source":       {"source_id": [note, ...]},
        }
    }

    Both slices are served from cache after the first call.
    A notes write never triggers a groups re-read and vice-versa.
    """
    _ensure_groups_loaded(thesis_id)
    _ensure_notes_loaded("source_group", thesis_id)
    _ensure_notes_loaded("source", thesis_id)

    groups_data = sorted(_groups_cache.values(), key=lambda g: g.get("group_id", ""))
    notes_data = {
        "source_group": _notes_cache.get("source_group", {}),
        "source":       _notes_cache.get("source", {}),
    }
    return {"groups": groups_data, "notes": notes_data}


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def list_notes(scope: str, entity_id: str, thesis_id: str = "") -> list[dict]:
    _ensure_notes_loaded(scope, thesis_id)
    return _notes_cache.get(scope, {}).get(entity_id, [])

def read_note(scope: str, note_id: str, thesis_id: str = "") -> Optional[dict]:
    return _read(_notes_dir(scope, thesis_id) / f"{note_id}.json")

def write_note(scope: str, note_id: str, data: dict, thesis_id: str = "") -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_notes_dir(scope, thesis_id) / f"{note_id}.json", data)
    entity_id = data.get("entity_id")
    if entity_id:
        _upsert_note_in_cache(scope, entity_id, data, thesis_id)
    return data

def delete_note(scope: str, note_id: str, thesis_id: str = "") -> bool:
    path = _notes_dir(scope, thesis_id) / f"{note_id}.json"
    if not path.exists():
        return False
    note = _read(path)
    path.unlink()
    if note:
        entity_id = note.get("entity_id")
        if entity_id:
            _evict_note(scope, entity_id, note_id, thesis_id)
    return True

# ---------------------------------------------------------------------------
# Misc key-value store
# ---------------------------------------------------------------------------

def read_misc(key: str) -> Optional[dict]:
    safe_key = key.replace("/", "_").replace("\\", "_")
    return _read(_misc_dir() / f"{safe_key}.json")


def write_misc(key: str, data: dict) -> dict:
    safe_key = key.replace("/", "_").replace("\\", "_")
    _write(_misc_dir() / f"{safe_key}.json", data)
    if safe_key == "drive_scan_result":
        _invalidate_drive_scan()
    return data


# ---------------------------------------------------------------------------
# Section Draft Storage
# ---------------------------------------------------------------------------

def read_section_draft(chapter_id: str, subtopic_id: str) -> Optional[dict]:
    return _read(_drafts_dir(chapter_id) / f"{subtopic_id}_draft.json")


def write_section_draft(chapter_id: str, subtopic_id: str, data: dict) -> dict:
    _write(_drafts_dir(chapter_id) / f"{subtopic_id}_draft.json", data)
    return data


def delete_section_draft(chapter_id: str, subtopic_id: str) -> bool:
    path = _drafts_dir(chapter_id) / f"{subtopic_id}_draft.json"
    if path.exists():
        path.unlink()
        return True
    return False


def read_nlm_state(chapter_id: str, subtopic_id: str) -> Optional[dict]:
    return _read(_nlm_state_dir(chapter_id) / f"{subtopic_id}_nlm_state.json")


def write_nlm_state(chapter_id: str, subtopic_id: str, data: dict) -> dict:
    _write(_nlm_state_dir(chapter_id) / f"{subtopic_id}_nlm_state.json", data)
    return data


def delete_nlm_state(chapter_id: str, subtopic_id: str) -> bool:
    path = _nlm_state_dir(chapter_id) / f"{subtopic_id}_nlm_state.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Batch State Storage
# ---------------------------------------------------------------------------

def write_batch_state(batch_id: str, data: dict) -> dict:
    """
    Persist batch manifest to misc storage.
    Key: batch_{batch_id} → spo_data/misc/batch_{batch_id}.json
    The manifest stores the subtopic list and worker split.
    Individual subtopic progress is NOT stored here — read each
    subtopic's own nlm_state file and aggregate at query time.
    """
    _write(_misc_dir() / f"batch_{batch_id}.json", data)
    return data


def read_batch_state(batch_id: str) -> Optional[dict]:
    """Read batch manifest. Returns None if batch_id is unknown."""
    return _read(_misc_dir() / f"batch_{batch_id}.json")


# ---------------------------------------------------------------------------
# Drive Link Resolution
# ---------------------------------------------------------------------------

def resolve_source_files(
    thesis_name: str,
    chapter_id_raw: str,
    scan: Optional[dict] = None,
) -> list[dict]:
    """
    Resolve source_ids and chapter references to local filenames and Drive links.
    Matching logic lives in services/source_resolver.py.

    `scan` is accepted for call-site compatibility but ignored — the drive scan
    result is held in _drive_scan_cache and read from disk at most once per
    process lifetime, so callers in a loop pay zero extra disk reads.
    """
    from services.source_resolver import resolve_source_files as _resolve
    return _resolve(thesis_name, chapter_id_raw, _get_drive_scan())