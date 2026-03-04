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
"""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Any


# Base data directory — override with SPO_DATA_DIR env var
DATA_DIR = Path(os.environ.get("SPO_DATA_DIR", Path.home() / "spo_data"))


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _thesis_dir() -> Path:
    return _ensure(DATA_DIR / "thesis_context")


def _chapters_dir() -> Path:
    return _ensure(DATA_DIR / "thesis_context" / "chapters")


def _groups_dir() -> Path:
    return _ensure(DATA_DIR / "source_groups")


def _group_dir(group_id: str) -> Path:
    return _ensure(DATA_DIR / "source_groups" / group_id)


def _sources_dir(group_id: str) -> Path:
    return _ensure(DATA_DIR / "source_groups" / group_id / "sources")


def _chain_dir(chapter_id: str) -> Path:
    return _ensure(DATA_DIR / "consistency_chain" / chapter_id)


# --- Generic read/write ---

def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _list_json(directory: Path) -> list[dict]:
    if not directory.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


# --- Synopsis ---

def read_synopsis() -> Optional[dict]:
    return _read(_thesis_dir() / "synopsis.json")


def write_synopsis(data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_thesis_dir() / "synopsis.json", data)
    return data


# --- Chapters ---

def list_chapters() -> list[dict]:
    return _list_json(_chapters_dir())


def read_chapter(chapter_id: str) -> Optional[dict]:
    return _read(_chapters_dir() / f"{chapter_id}.json")


def write_chapter(chapter_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_chapters_dir() / f"{chapter_id}.json", data)
    return data


def delete_chapter(chapter_id: str) -> bool:
    path = _chapters_dir() / f"{chapter_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# --- Source Groups ---

def list_source_groups() -> list[dict]:
    groups_dir = _groups_dir()
    if not groups_dir.exists():
        return []
    result = []
    for group_path in sorted(groups_dir.iterdir()):
        if group_path.is_dir():
            meta = _read(group_path / "group_meta.json")
            if meta:
                result.append(meta)
    return result


def read_source_group(group_id: str) -> Optional[dict]:
    meta = _read(_group_dir(group_id) / "group_meta.json")
    if not meta:
        return None
    # Embed sources into the group response
    meta["sources"] = list_sources(group_id)
    return meta


def write_source_group(group_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    # Don't store sources inside group_meta — they live in their own files
    sources = data.pop("sources", [])
    _write(_group_dir(group_id) / "group_meta.json", data)
    data["sources"] = sources
    return data


def delete_source_group(group_id: str) -> bool:
    group_path = _group_dir(group_id)
    if group_path.exists():
        shutil.rmtree(group_path)
        return True
    return False


# --- Sources ---

def list_sources(group_id: str) -> list[dict]:
    return _list_json(_sources_dir(group_id))


def read_source(group_id: str, source_id: str) -> Optional[dict]:
    return _read(_sources_dir(group_id) / f"{source_id}.json")


def write_source(group_id: str, source_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_sources_dir(group_id) / f"{source_id}.json", data)
    return data


def delete_source(group_id: str, source_id: str) -> bool:
    path = _sources_dir(group_id) / f"{source_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# --- Index Cards (stored within source file) ---

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


# --- Consistency Chain ---

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


# --- Cross-cutting: find sources by subtopic ---

def find_sources_for_subtopic(subtopic_id: str) -> list[dict]:
    """
    Scan all index cards across all source groups and return sources
    whose index_card.relevant_subtopics includes this subtopic_id.
    Used for auto-suggesting sources when compiling prompts.
    """
    matches = []
    groups_dir = _groups_dir()
    if not groups_dir.exists():
        return matches
    for group_path in groups_dir.iterdir():
        if not group_path.is_dir():
            continue
        sources_path = group_path / "sources"
        if not sources_path.exists():
            continue
        for source_file in sources_path.glob("*.json"):
            source = json.loads(source_file.read_text(encoding="utf-8"))
            card = source.get("index_card")
            if card and subtopic_id in card.get("relevant_subtopics", []):
                matches.append(source)
    return matches


def find_sources_by_theme(theme: str) -> list[dict]:
    """
    Find all sources whose index card contains a specific theme tag.
    """
    matches = []
    groups_dir = _groups_dir()
    if not groups_dir.exists():
        return matches
    for group_path in groups_dir.iterdir():
        if not group_path.is_dir():
            continue
        sources_path = group_path / "sources"
        if not sources_path.exists():
            continue
        for source_file in sources_path.glob("*.json"):
            source = json.loads(source_file.read_text(encoding="utf-8"))
            card = source.get("index_card")
            if card and theme in card.get("themes", []):
                matches.append(source)
    return matches


# --- Notes (free-text scratch pad per entity) ---

def _notes_dir(scope: str) -> Path:
    return _ensure(DATA_DIR / "notes" / scope)


def list_notes(scope: str, entity_id: str) -> list[dict]:
    notes_dir = _notes_dir(scope)
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(notes_dir.glob(f"{entity_id}_*.json"))
    ]


def read_note(scope: str, note_id: str) -> Optional[dict]:
    # note_id encodes entity: e.g. "grp123_n001"
    # We store as {note_id}.json directly under scope dir
    return _read(_notes_dir(scope) / f"{note_id}.json")


def write_note(scope: str, note_id: str, data: dict) -> dict:
    data["updated_at"] = datetime.utcnow().isoformat()
    _write(_notes_dir(scope) / f"{note_id}.json", data)
    return data


def delete_note(scope: str, note_id: str) -> bool:
    path = _notes_dir(scope) / f"{note_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False