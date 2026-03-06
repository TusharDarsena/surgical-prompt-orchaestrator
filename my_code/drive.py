"""
Drive Router
------------
Two responsibilities:
  1. Local filesystem scan — discovers thesis folders and PDFs from a local path
  2. Google Drive link registration — fetches file IDs from a Drive folder and
     stores shareable links per filename, so the compiler can resolve source_ids
     to clickable links

Expected folder structure (local):
    parent_folder/
        my_thesis_1/
            my_thesis_1_sources/
                actual_thesis_folder/     ← level-4: thesis name
                    07_chapter 1.pdf
                    08_chapter 2.pdf
            index_cards/                  ← created by app if missing
                actual_thesis_folder.json

Google Drive structure (mirrors local):
    phd/
        my_thesis_1/
            original_sources/
                actual_thesis_folder/
                    07_chapter 1.pdf

Endpoints:
    POST /drive/scan-local              ← scan local parent folder
    GET  /drive/local-files             ← return stored file tree + link status
    POST /drive/save-index-card         ← save JSON + auto-import to SPO
    POST /drive/register-links          ← fetch Drive file IDs → store shareable links
    GET  /drive/links/{thesis_name}     ← return stored links for one thesis
    DELETE /drive/links/{thesis_name}   ← clear stored links (force re-register)

Setup required:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

    Credentials: set GOOGLE_SERVICE_ACCOUNT_JSON env var to the path of your
    service account JSON file, OR set GOOGLE_DRIVE_API_KEY for API key auth.

    For a service account:
      1. Create a service account in Google Cloud Console
      2. Enable the Drive API
      3. Share the parent Drive folder with the service account email (viewer access)
      4. Download the JSON key file
      5. Set GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json

    For API key (simpler, read-only public folders only):
      1. Create an API key in Google Cloud Console with Drive API access
      2. Set GOOGLE_DRIVE_API_KEY=your_key_here
      3. Make sure the Drive folder is publicly accessible (Anyone with link → Viewer)
"""

import os
import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services import storage

router = APIRouter(prefix="/drive", tags=["Drive & Local Scanner"])

# ── Storage keys ───────────────────────────────────────────────────────────────
SCAN_KEY = "drive_scan_result"
IMPORT_STATUS_KEY = "drive_import_status"
LINKS_KEY_PREFIX = "drive_links_"  # + thesis_name


def _read_scan() -> dict:
    data = storage.read_misc(SCAN_KEY)
    return data if data else {}


def _write_scan(data: dict):
    storage.write_misc(SCAN_KEY, data)


def _read_import_status() -> dict:
    data = storage.read_misc(IMPORT_STATUS_KEY)
    return data if data else {}


def _write_import_status(data: dict):
    storage.write_misc(IMPORT_STATUS_KEY, data)


def _links_key(thesis_name: str) -> str:
    # Sanitize for use as a storage key (no spaces, slashes, quotes)
    safe = thesis_name.replace(" ", "_").replace("/", "-").replace("\\", "-")
    return f"{LINKS_KEY_PREFIX}{safe[:100]}"


# ── Models ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    root_path: str


class SaveIndexCardRequest(BaseModel):
    thesis_name: str
    level2_path: str
    json_text: str


class RegisterLinksRequest(BaseModel):
    # The Google Drive folder ID of the PARENT folder —
    # the same top-level folder you configured in scan-local.
    # Drive structure expected (mirrors local):
    #   parent_folder/               ← pass THIS folder's ID
    #     my_thesis_1/
    #       my_thesis_1_sources/
    #         actual_thesis_folder/  ← level-4, matched to thesis_name in scan
    #           07_chapter 1.pdf
    drive_parent_folder_id: str


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE DRIVE LINK REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/register-links", summary="Walk Drive parent folder and register shareable links for all thesis folders")
def register_drive_links(req: RegisterLinksRequest):
    """
    Walks the Drive parent folder (4 levels deep, mirroring the local structure)
    and for every level-4 thesis folder found, fetches all PDF file IDs and
    stores shareable links as { filename: link }.

    Drive structure walked:
      parent/                        level-1 (drive_parent_folder_id)
        my_thesis_1/                 level-2
          my_thesis_1_sources/       level-3 (any folder at this level)
            actual_thesis_folder/    level-4 → matched to thesis_name in local scan
              07_chapter 1.pdf       → registered

    Only thesis names already present in the local scan are registered.
    Unknown Drive folders are skipped and reported.
    Results are stored and used automatically by resolve_source_files().
    """
    service = _get_drive_service()
    scan = _read_scan()

    registered = []   # { thesis_name, files_registered }
    skipped = []      # { folder_name, reason }

    # ── Level-2: list folders inside parent ───────────────────────────────────
    l2_folders = _list_drive_folders(service, req.drive_parent_folder_id)
    if l2_folders is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not list Drive folder '{req.drive_parent_folder_id}'. Check folder ID and sharing settings."
        )

    for l2 in l2_folders:
        # ── Level-3: find the *_sources folder inside each level-2 ───────────
        l3_folders = _list_drive_folders(service, l2["id"])
        if l3_folders is None:
            skipped.append({"folder": l2["name"], "reason": "could not list level-3 subfolders"})
            continue

        # Mirror local logic: take the first folder at level-3 regardless of name
        # (local scan requires *_sources suffix but Drive may have slightly different names)
        if not l3_folders:
            skipped.append({"folder": l2["name"], "reason": "no level-3 subfolder found"})
            continue

        l3 = l3_folders[0]

        # ── Level-4: thesis folders inside sources folder ─────────────────────
        l4_folders = _list_drive_folders(service, l3["id"])
        if l4_folders is None:
            skipped.append({"folder": l2["name"], "reason": "could not list level-4 thesis folders"})
            continue

        for l4 in l4_folders:
            thesis_name = l4["name"]

            # Only register theses that exist in the local scan
            if thesis_name not in scan:
                # Try case-insensitive match
                matched = next(
                    (k for k in scan if k.lower() == thesis_name.lower()),
                    None
                )
                if not matched:
                    skipped.append({
                        "folder": thesis_name,
                        "reason": "not in local scan — run scan-local first or check folder name"
                    })
                    continue
                thesis_name = matched  # use the scan key casing

            # ── Fetch PDF files inside level-4 ────────────────────────────────
            files = _list_drive_files(service, l4["id"])
            if files is None:
                skipped.append({"folder": thesis_name, "reason": "could not list files in Drive folder"})
                continue

            if not files:
                skipped.append({"folder": thesis_name, "reason": "no files found in Drive folder"})
                continue

            # Build filename → shareable link
            links = {
                f["name"]: f"https://drive.google.com/file/d/{f['id']}/view"
                for f in files
            }

            # Persist links
            storage.write_misc(_links_key(thesis_name), links)

            # Also write into scan entry for resolve_source_files()
            scan[thesis_name]["drive_links"] = links
            scan[thesis_name]["drive_links_registered_at"] = datetime.utcnow().isoformat()
            scan[thesis_name]["drive_folder_id"] = l4["id"]

            registered.append({
                "thesis_name": thesis_name,
                "drive_folder_id": l4["id"],
                "files_registered": len(links),
            })

    _write_scan(scan)

    return {
        "registered_count": len(registered),
        "skipped_count": len(skipped),
        "registered": registered,
        "skipped": skipped,
    }


@router.get("/links/{thesis_name}", summary="Return stored Drive links for a thesis")
def get_drive_links(thesis_name: str):
    links = storage.read_misc(_links_key(thesis_name))
    if not links:
        raise HTTPException(
            status_code=404,
            detail=f"No Drive links registered for '{thesis_name}'. Use POST /drive/register-links first."
        )
    return {
        "thesis_name": thesis_name,
        "count": len(links),
        "links": links,
    }


@router.delete("/links/{thesis_name}", summary="Clear stored Drive links for a thesis (force re-register)")
def delete_drive_links(thesis_name: str):
    existing = storage.read_misc(_links_key(thesis_name))
    if not existing:
        raise HTTPException(status_code=404, detail=f"No links found for '{thesis_name}'.")

    storage.write_misc(_links_key(thesis_name), {})

    scan = _read_scan()
    if thesis_name in scan:
        scan[thesis_name].pop("drive_links", None)
        scan[thesis_name].pop("drive_links_registered_at", None)
        scan[thesis_name].pop("drive_folder_id", None)
        _write_scan(scan)

    return {"deleted": True, "thesis_name": thesis_name}


# ── Drive API helpers ──────────────────────────────────────────────────────────

def _list_drive_folders(service, folder_id: str) -> list | None:
    """Returns list of {id, name} for subfolders of folder_id. None on error."""
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)",
            pageSize=100,
        ).execute()
        return results.get("files", [])
    except Exception:
        return None


def _list_drive_files(service, folder_id: str) -> list | None:
    """Returns list of {id, name} for files (non-folders) in folder_id. None on error."""
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            fields="files(id, name)",
            pageSize=100,
        ).execute()
        return results.get("files", [])
    except Exception:
        return None


# ── Drive API client ───────────────────────────────────────────────────────────

def _get_drive_service():
    """
    Returns an authenticated Google Drive API service object.
    Tries service account first, falls back to API key.
    Raises HTTPException with a clear message if neither is configured.
    """
    service_account_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    api_key = os.environ.get("GOOGLE_DRIVE_API_KEY")

    if not service_account_path and not api_key:
        raise HTTPException(
            status_code=500,
            detail=(
                "Google Drive credentials not configured. "
                "Set GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/key.json "
                "or GOOGLE_DRIVE_API_KEY=your_key in your environment variables. "
                "See drive.py module docstring for full setup instructions."
            )
        )

    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "google-api-python-client not installed. "
                "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )
        )

    if service_account_path:
        # Service account auth — works for both public and private folders
        try:
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(
                service_account_path,
                scopes=["https://www.googleapis.com/auth/drive.readonly"]
            )
            return build("drive", "v3", credentials=creds)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Service account auth failed: {e}. Check GOOGLE_SERVICE_ACCOUNT_JSON path."
            )

    # API key auth — only works for publicly shared folders
    try:
        return build("drive", "v3", developerKey=api_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"API key auth failed: {e}. Check GOOGLE_DRIVE_API_KEY value."
        )


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-IMPORT HELPER (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def _auto_import(data: dict):
    from routers.importer import _normalize_source_chapter, SourceImport
    from pydantic import ValidationError

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
