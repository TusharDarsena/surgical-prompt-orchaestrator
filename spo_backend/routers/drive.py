"""
Drive Router (Local Filesystem)
--------------------------------
Scans a local directory tree to discover thesis source folders and their PDFs.
Handles saving NotebookLM JSON output as index card files and auto-importing them.

Expected folder structure:
    parent_folder/
        my_thesis_1/
            my_thesis_1_sources/
                actual_thesis_folder/     ← level-4: thesis name, used as section header
                    07_chapter 1.pdf
                    08_chapter 2.pdf
            index_cards/                  ← created by app if missing
                actual_thesis_folder.json ← saved JSON per thesis

Endpoints:
    POST /drive/scan-local          ← scan parent folder, store file tree
    GET  /drive/local-files         ← return stored file tree
    POST /drive/save-index-card     ← save JSON + auto-import to SPO
"""

import os
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services import storage

router = APIRouter(prefix="/drive", tags=["Local File Scanner"])

# ── Storage helpers ────────────────────────────────────────────────────────────
# We store the scan result and import status as two separate JSON files
# in the SPO data directory so rescans don't clobber import status.

SCAN_KEY = "drive_scan_result"
IMPORT_STATUS_KEY = "drive_import_status"


def _read_scan() -> dict:
    """Returns { thesis_name: { files: [...], level2_path: "...", level3_path: "..." } }"""
    data = storage.read_misc(SCAN_KEY)
    return data if data else {}


def _write_scan(data: dict):
    storage.write_misc(SCAN_KEY, data)


def _read_import_status() -> dict:
    """Returns { thesis_name: { imported: bool, imported_at: str, group_id: str, error: str } }"""
    data = storage.read_misc(IMPORT_STATUS_KEY)
    return data if data else {}


def _write_import_status(data: dict):
    storage.write_misc(IMPORT_STATUS_KEY, data)


# ── Models ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    root_path: str  # e.g. C:\Users\TUSHAR\Downloads\Shodhganga_Downloads


class SaveIndexCardRequest(BaseModel):
    thesis_name: str        # level-4 folder name — used as filename and lookup key
    level2_path: str        # absolute path to my_thesis_1 — needed to find index_cards dir
    json_text: str          # raw JSON string pasted from NotebookLM


# ── Scan endpoint ──────────────────────────────────────────────────────────────

@router.post("/scan-local", summary="Scan parent folder and build thesis file tree")
def scan_local(req: ScanRequest):
    root = req.root_path.strip()

    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Path not found or not a directory: {root}")

    existing_scan = _read_scan()
    added = []
    skipped = []

    # Walk level-2 folders (my_thesis_1, my_thesis_2, ...)
    try:
        level2_entries = [
            e for e in os.scandir(root)
            if e.is_dir()
        ]
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied reading {root}: {e}")

    for l2 in level2_entries:
        # Find the single level-3 *_sources folder inside level-2
        try:
            l3_candidates = [
                e for e in os.scandir(l2.path)
                if e.is_dir() and e.name.endswith("_sources")
            ]
        except PermissionError:
            skipped.append({"folder": l2.name, "reason": "permission denied at level-3"})
            continue

        if not l3_candidates:
            # No *_sources folder found — skip this level-2 dir silently
            # (could be a drafts or output folder, not a sources container)
            continue

        l3 = l3_candidates[0]  # always a single *_sources folder per design

        # Walk level-4 folders (actual thesis folders)
        try:
            l4_entries = [e for e in os.scandir(l3.path) if e.is_dir()]
        except PermissionError:
            skipped.append({"folder": l2.name, "reason": "permission denied at level-4"})
            continue

        for l4 in l4_entries:
            thesis_name = l4.name

            # Collect PDF files inside level-4
            try:
                pdfs = sorted([
                    f.name for f in os.scandir(l4.path)
                    if f.is_file() and f.name.lower().endswith(".pdf")
                ])
            except PermissionError:
                skipped.append({"folder": thesis_name, "reason": "permission denied reading PDFs"})
                continue

            if thesis_name in existing_scan:
                # On rescan: update file list but keep everything else intact
                existing_scan[thesis_name]["files"] = pdfs
                existing_scan[thesis_name]["rescanned_at"] = datetime.utcnow().isoformat()
                skipped.append({"folder": thesis_name, "reason": "already exists — file list updated"})
            else:
                existing_scan[thesis_name] = {
                    "thesis_name": thesis_name,
                    "level2_path": l2.path,
                    "level3_path": l3.path,
                    "level4_path": l4.path,
                    "files": pdfs,
                    "scanned_at": datetime.utcnow().isoformat(),
                }
                added.append(thesis_name)

    _write_scan(existing_scan)

    return {
        "total_thesis_folders": len(existing_scan),
        "newly_added": len(added),
        "added": added,
        "skipped": skipped,
    }


@router.get("/local-files", summary="Return stored file tree from last scan")
def get_local_files():
    scan = _read_scan()
    import_status = _read_import_status()

    result = []
    for thesis_name, data in scan.items():
        entry = dict(data)
        status = import_status.get(thesis_name, {})
        entry["imported"] = status.get("imported", False)
        entry["imported_at"] = status.get("imported_at")
        entry["import_group_id"] = status.get("group_id")
        entry["import_error"] = status.get("error")
        result.append(entry)

    # Sort alphabetically by thesis name
    result.sort(key=lambda x: x["thesis_name"].lower())
    return {"thesis_folders": result, "count": len(result)}


# ── Save + auto-import endpoint ────────────────────────────────────────────────

@router.post("/save-index-card", summary="Save NotebookLM JSON to disk and auto-import to SPO")
def save_index_card(req: SaveIndexCardRequest):
    scan = _read_scan()

    if req.thesis_name not in scan:
        raise HTTPException(
            status_code=404,
            detail=f"Thesis '{req.thesis_name}' not found in scan. Run scan first."
        )

    thesis_entry = scan[req.thesis_name]
    level2_path = thesis_entry["level2_path"]

    # Parse JSON first — fail early before touching disk
    try:
        parsed = json.loads(req.json_text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid JSON: {e}. File not saved. Fix the JSON and try again."
        )

    # Create index_cards folder inside level-2 if it doesn't exist
    index_cards_dir = os.path.join(level2_path, "index_cards")
    os.makedirs(index_cards_dir, exist_ok=True)

    # Save JSON file named after thesis folder
    # Sanitize thesis name for use as filename (replace path-unsafe chars)
    safe_name = req.thesis_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    json_path = os.path.join(index_cards_dir, f"{safe_name}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    # Auto-import to SPO via the same logic as import_source in importer.py
    # We call it directly rather than making an internal HTTP request
    import_result, import_error = _auto_import(parsed)

    # Record import status regardless of success — file is always saved
    import_status = _read_import_status()
    import_status[req.thesis_name] = {
        "imported": import_result is not None,
        "imported_at": datetime.utcnow().isoformat() if import_result else None,
        "group_id": import_result.get("group_id") if import_result else None,
        "error": import_error,
        "json_path": json_path,
    }
    _write_import_status(import_status)

    if import_error:
        return {
            "saved": True,
            "json_path": json_path,
            "imported": False,
            "import_error": import_error,
            "message": "JSON saved to disk. Import failed — fix and re-import manually from the Source Library import tab.",
        }

    return {
        "saved": True,
        "json_path": json_path,
        "imported": True,
        "group_id": import_result["group_id"],
        "sources_created": import_result["sources_created"],
        "message": f"Saved and imported. {import_result['sources_created']} sources created.",
    }


def _auto_import(data: dict):
    """
    Runs the same import logic as POST /import/source.
    Returns (result_dict, error_string). One of the two will always be None.

    We import directly rather than making an internal HTTP call to avoid
    needing the server to call itself. If importer.py logic changes,
    keep this in sync with import_source() in importer.py.
    """
    from routers.importer import _normalize_source_chapter
    from pydantic import ValidationError
    from routers.importer import SourceImport

    # Normalize chapter fields (same as import_source does)
    if "chapters" in data:
        data["chapters"] = [_normalize_source_chapter(ch) for ch in data["chapters"]]

    try:
        validated = SourceImport(**data)
    except ValidationError as e:
        return None, f"Validation failed: {e.errors()}"

    valid_types = {"thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"}
    if validated.source_type not in valid_types:
        return None, f"source_type must be one of: {', '.join(valid_types)}"

    group_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()

    group_record = {
        "group_id": group_id,
        "title": validated.title,
        "author": validated.author,
        "year": validated.year,
        "source_type": validated.source_type,
        "institution_or_publisher": validated.institution_or_publisher,
        "description": validated.description,
        "work_summary": validated.work_summary,
        "created_at": now,
        "updated_at": now,
    }
    storage.write_source_group(group_id, group_record)

    created_sources = []
    for ch in validated.chapters:
        source_id = str(uuid.uuid4())[:8]
        source_record = {
            "source_id": source_id,
            "group_id": group_id,
            "label": ch.label,
            "title": ch.title,
            "chapter_or_section": ch.title,
            "page_range": ch.page_range,
            "file_name": ch.file_name,
            "file_path": None,
            "index_card": None,
            "has_index_card": False,
            "created_at": now,
            "updated_at": now,
        }
        index_card = {
            "key_claims": ch.key_claims,
            "themes": ch.themes,
            "time_period_covered": ch.time_period_covered,
            "relevant_subtopics": ch.relevant_subtopics,
            "limitations": ch.limitations,
            "notable_authors_cited": ch.notable_authors_cited,
            "your_notes": None,
            "created_at": now,
            "updated_at": now,
        }
        source_record["index_card"] = index_card
        source_record["has_index_card"] = True
        storage.write_source(group_id, source_id, source_record)
        created_sources.append({"source_id": source_id, "label": ch.label})

    return {
        "group_id": group_id,
        "title": validated.title,
        "author": validated.author,
        "sources_created": len(created_sources),
        "sources": created_sources,
    }, None
