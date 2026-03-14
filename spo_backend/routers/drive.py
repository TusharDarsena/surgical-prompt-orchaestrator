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

Security:
    scan-local accepts root_path from the client. To prevent path traversal,
    set the environment variable SPO_SCAN_BASE_DIR to the absolute path of your
    allowed scan root (e.g. D:\\PhD). Requests for paths outside that directory
    are rejected with HTTP 400.  If SPO_SCAN_BASE_DIR is not set, only the
    standard is_dir() check is performed (original behavior).

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
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from services import storage
from services.source_importer import do_auto_import  # top-level — no circular dep


router = APIRouter(prefix="/drive", tags=["Drive & Local Scanner"])

# ── Storage key ────────────────────────────────────────────────────────────────
# Single key holds ALL per-thesis state: scan data, import status, drive links.
SCAN_KEY = "drive_scan_result"

# ── Path traversal guard ───────────────────────────────────────────────────────
# Set SPO_SCAN_BASE_DIR env var to restrict which directories clients may scan.
# Leave unset to skip the restriction (any valid local directory is allowed).
_BASE_SCAN_DIR_ENV = os.environ.get("SPO_SCAN_BASE_DIR", "").strip()
BASE_SCAN_DIR: Path | None = Path(_BASE_SCAN_DIR_ENV).resolve() if _BASE_SCAN_DIR_ENV else None


def _read_scan() -> dict:
    data = storage.read_misc(SCAN_KEY)
    return data if data else {}


def _write_scan(data: dict):
    storage.write_misc(SCAN_KEY, data)


def _empty_thesis_entry(thesis_name: str, folder_path: str) -> dict:
    """Returns a fully-initialised unified thesis object."""
    return {
        "thesis_name": thesis_name,
        "folder_path": folder_path,
        "files": [],
        "scanned_at": datetime.utcnow().isoformat(),
        # ── import status sub-object ──────────────────────────────────────────
        "import_status": {
            "imported": False,
            "imported_at": None,
            "group_id": None,
            "error": None,
            "json_path": None,
        },
        # ── drive links sub-object ────────────────────────────────────────────
        "drive_links": {},
        "drive_links_registered_at": None,
        "drive_folder_id": None,
    }


# ── Models ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    root_path: str


class SaveIndexCardRequest(BaseModel):
    thesis_name: str
    # 'data' receives the parsed JSON object directly — FastAPI/Pydantic handles
    # deserialization, so no manual json.loads() + JSONDecodeError is needed.
    data: dict


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
# LOCAL SCAN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/scan-local")
def scan_local(req: ScanRequest):
    # ── Fix 2: path traversal guard ───────────────────────────────────────────
    root = Path(req.root_path.strip()).resolve()

    if BASE_SCAN_DIR is not None and not root.is_relative_to(BASE_SCAN_DIR):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Path '{req.root_path}' is outside the allowed scan directory. "
                "Set SPO_SCAN_BASE_DIR to the base path you want to restrict scanning to."
            )
        )

    if not root.is_dir():
        raise HTTPException(status_code=400, detail="Invalid directory — path does not exist or is not a folder.")

    existing_scan = _read_scan()
    added = []

    # 1. Find EVERY PDF in the entire tree, regardless of depth
    pdf_files = list(root.rglob("*.pdf"))

    # 2. Group PDFs by their parent directory
    thesis_folders: dict[Path, list[str]] = {}
    for pdf in pdf_files:
        parent_dir = pdf.parent
        thesis_folders.setdefault(parent_dir, []).append(pdf.name)

    # 3. Process the discovered folders
    for folder_path, pdfs in thesis_folders.items():
        thesis_name = folder_path.name

        if thesis_name in existing_scan:
            existing_scan[thesis_name]["files"] = sorted(pdfs)
            existing_scan[thesis_name]["rescanned_at"] = datetime.utcnow().isoformat()
        else:
            entry = _empty_thesis_entry(thesis_name, str(folder_path))
            entry["files"] = sorted(pdfs)
            existing_scan[thesis_name] = entry
            added.append(thesis_name)

    _write_scan(existing_scan)
    return {"added": added, "total": len(existing_scan)}


@router.get("/local-files", summary="Return stored file tree with Drive link status")
def get_local_files():
    # ── Fix 3: single storage read — all state lives in the unified scan dict ─
    scan = _read_scan()

    result = []
    for thesis_name, data in scan.items():
        entry = dict(data)

        # Flatten import_status sub-object for the API response
        status = entry.pop("import_status", {})
        entry["imported"] = status.get("imported", False)
        entry["imported_at"] = status.get("imported_at")
        entry["import_group_id"] = status.get("group_id")
        entry["import_error"] = status.get("error")

        # Flatten drive_links sub-object
        links = entry.get("drive_links", {})
        entry["drive_links_registered"] = bool(links)
        entry["drive_links_count"] = len(links)

        result.append(entry)

    result.sort(key=lambda x: x["thesis_name"].lower())
    return {"thesis_folders": result, "count": len(result)}


@router.post("/save-index-card", summary="Save NotebookLM JSON to disk and auto-import to SPO")
def save_index_card(req: SaveIndexCardRequest):
    scan = _read_scan()

    if req.thesis_name not in scan:
        raise HTTPException(
            status_code=404,
            detail=f"Thesis '{req.thesis_name}' not found in scan. Run scan first."
        )

    thesis_entry = scan[req.thesis_name]

    # req.data is already a parsed dict — no json.loads() needed (Fix 1)
    parsed = req.data

    level2_path = thesis_entry.get("folder_path", "")
    index_cards_dir = os.path.join(level2_path, "index_cards")
    os.makedirs(index_cards_dir, exist_ok=True)

    safe_name = req.thesis_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    json_path = os.path.join(index_cards_dir, f"{safe_name}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    import_result, import_error = do_auto_import(parsed)  # Fix 4: top-level import

    # ── Fix 3: write import status into the unified scan object ───────────────
    thesis_entry["import_status"] = {
        "imported": import_result is not None,
        "imported_at": datetime.utcnow().isoformat() if import_result else None,
        "group_id": import_result.get("group_id") if import_result else None,
        "error": import_error,
        "json_path": json_path,
    }
    _write_scan(scan)

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
    Results are stored inside the unified scan object and used automatically
    by resolve_source_files().
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

            # ── Fetch files inside level-4 ────────────────────────────────────
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

            # ── Fix 3: write directly into the unified scan entry ─────────────
            scan[thesis_name]["drive_links"] = links
            scan[thesis_name]["drive_links_registered_at"] = datetime.utcnow().isoformat()
            scan[thesis_name]["drive_folder_id"] = l4["id"]

            registered.append({
                "thesis_name": thesis_name,
                "drive_folder_id": l4["id"],
                "files_registered": len(links),
            })

    _write_scan(scan)  # single write covers all registered theses

    return {
        "registered_count": len(registered),
        "skipped_count": len(skipped),
        "registered": registered,
        "skipped": skipped,
    }


@router.get("/links/{thesis_name}", summary="Return stored Drive links for a thesis")
def get_drive_links(thesis_name: str):
    scan = _read_scan()
    entry = scan.get(thesis_name)
    links = entry.get("drive_links", {}) if entry else {}
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
    scan = _read_scan()
    if thesis_name not in scan or not scan[thesis_name].get("drive_links"):
        raise HTTPException(status_code=404, detail=f"No links found for '{thesis_name}'.")

    # ── Fix 3: clear within the unified scan entry — single write ─────────────
    scan[thesis_name]["drive_links"] = {}
    scan[thesis_name]["drive_links_registered_at"] = None
    scan[thesis_name]["drive_folder_id"] = None
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