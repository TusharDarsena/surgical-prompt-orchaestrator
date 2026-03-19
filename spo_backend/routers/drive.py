"""
Drive Router
------------
Two responsibilities:
  1. Local filesystem scan — discovers thesis folders and PDFs from a local path
  2. Google Drive link registration — fetches file IDs from a Drive folder and
     stores shareable links per filename, so the compiler can resolve source_ids
     to clickable links

Expected folder structure (local):
    Any directory structure is supported. scan-local uses rglob to find every
    PDF in the tree and groups them by their immediate parent folder.

Google Drive structure:
    Any structure is supported. register-links recursively walks the Drive
    parent folder at any depth and matches leaf folders (folders that contain
    files) to scan keys by folder name.

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
    thesis_folder_name: Optional[str] = None  # when set, scopes scan to root/thesis_folder_name only


class SaveIndexCardRequest(BaseModel):
    thesis_name: str
    level2_path: str
    json_text: str

class RegisterLinksRequest(BaseModel):
    # The Google Drive folder ID of the parent folder — any structure beneath
    # it is supported. register-links walks recursively and matches leaf folders
    # (folders that directly contain files) to scan keys by folder name.
    drive_parent_folder_id: str


# ══════════════════════════════════════════════════════════════════════════════
# LOCAL SCAN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/scan-local")
def scan_local(req: ScanRequest):
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

    # If thesis_folder_name is provided, scope the scan to root/thesis_folder_name only.
    # This prevents the cleanup step from touching entries belonging to other theses.
    if req.thesis_folder_name:
        scan_root = root / req.thesis_folder_name
        if not scan_root.is_dir():
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Folder '{req.thesis_folder_name}' not found inside '{root}'. "
                    "Make sure the thesis title matches the Level 2 folder name exactly."
                )
            )
    else:
        scan_root = root  # legacy full-scan behaviour

    existing_scan = _read_scan()
    added = []

    # 1. Find EVERY PDF safely (case-insensitive to catch .PDF and .pdf)
    pdf_files = [p for p in scan_root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]

    # 2. Group PDFs by their parent directory
    thesis_folders: dict[Path, list[str]] = {}
    for pdf in pdf_files:
        parent_dir = pdf.parent
        thesis_folders.setdefault(parent_dir, []).append(pdf.name)

    # 3. CLEANUP STALE FOLDERS: Remove entries that were deleted from the filesystem
    current_thesis_names = {folder.name for folder in thesis_folders.keys()}
    keys_to_delete = []

    for t_name, t_data in existing_scan.items():
        # Get stored path (supporting both new and old key names)
        t_path_str = t_data.get("folder_path") or t_data.get("level2_path", "")
        if not t_path_str:
            continue

        t_path = Path(t_path_str)
        # Only consider entries whose folder lives inside scan_root (not the full root).
        # Scoped scans must never delete entries belonging to other theses.
        if t_path.is_relative_to(scan_root) and t_name not in current_thesis_names:
            keys_to_delete.append(t_name)

    # Delete the ghost folders
    for k in keys_to_delete:
        del existing_scan[k]

    # 4. Process the discovered folders
    for folder_path, pdfs in thesis_folders.items():
        thesis_name = folder_path.name

        if thesis_name in existing_scan:
            existing_scan[thesis_name]["files"] = sorted(pdfs)
            existing_scan[thesis_name]["rescanned_at"] = datetime.utcnow().isoformat()
            # Ensure path is updated just in case the folder was moved
            existing_scan[thesis_name]["folder_path"] = str(folder_path)
            existing_scan[thesis_name]["level2_path"] = str(folder_path) 
        else:
            entry = _empty_thesis_entry(thesis_name, str(folder_path))
            entry["files"] = sorted(pdfs)
            entry["level2_path"] = str(folder_path) # Legacy support for UI
            existing_scan[thesis_name] = entry
            added.append(thesis_name)

    _write_scan(existing_scan)
    
    return {
        "total_thesis_folders": len(existing_scan),
        "newly_added": len(added),
        "added": added,
        "skipped": [],
    }

@router.get("/local-files", summary="Return stored file tree with Drive link status")
def get_local_files():
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
 
    try:
        parsed = json.loads(req.json_text)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid JSON: {e}. File not saved. Fix the JSON and try again."
        )
 
    # Support both new scan entries (folder_path) and old ones (level2_path)
    level2_path = thesis_entry.get("folder_path") or thesis_entry.get("level2_path", "")
    index_cards_dir = os.path.join(level2_path, "index_cards")
    os.makedirs(index_cards_dir, exist_ok=True)

    safe_name = req.thesis_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    json_path = os.path.join(index_cards_dir, f"{safe_name}.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    import_result, import_error = do_auto_import(parsed, scan_key=req.thesis_name)

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

@router.post("/register-links", summary="Recursively walk Drive parent folder and register shareable links for all thesis folders")
def register_drive_links(req: RegisterLinksRequest):
    """
    Recursively walks the Drive parent folder at any depth. Any folder that
    directly contains files (not just subfolders) is treated as a thesis folder
    and matched to the local scan by folder name.

    This mirrors the rglob behaviour of scan-local — the Drive structure does
    not need to follow any specific depth or naming convention.

    Only thesis names already present in the local scan are registered.
    Unknown Drive folders are skipped and reported.
    Results are stored inside the unified scan object and used automatically
    by resolve_source_files().
    """
    service = _get_drive_service()
    scan = _read_scan()

    registered = []
    skipped = []

    # Recursively find all leaf folders (folders that contain files)
    _walk_drive_folder(
        service=service,
        folder_id=req.drive_parent_folder_id,
        scan=scan,
        registered=registered,
        skipped=skipped,
    )

    _write_scan(scan)

    return {
        "registered_count": len(registered),
        "skipped_count": len(skipped),
        "registered": registered,
        "skipped": skipped,
    }


def _walk_drive_folder(
    service,
    folder_id: str,
    scan: dict,
    registered: list,
    skipped: list,
):
    """
    Recursively walks a Drive folder. For each folder encountered:
      - If it contains files → treat it as a thesis folder, match to scan
      - If it contains subfolders → recurse into them
      - Both can be true (a folder can have files and subfolders)

    This makes the function depth-agnostic — any structure works.
    """
    # List subfolders
    subfolders = _list_drive_folders(service, folder_id)
    if subfolders is None:
        # Can't list this folder — skip silently (already logged at call site)
        return

    # Recurse into subfolders first
    for subfolder in subfolders:
        _walk_drive_folder(
            service=service,
            folder_id=subfolder["id"],
            scan=scan,
            registered=registered,
            skipped=skipped,
        )

    # Check if this folder directly contains files
    files = _list_drive_files(service, folder_id)
    if not files:
        return  # no files here — not a thesis folder

    # Need the folder's own name to match against scan keys.
    # We get it from the Drive API metadata.
    folder_meta = _get_folder_metadata(service, folder_id)
    if not folder_meta:
        skipped.append({
            "folder_id": folder_id,
            "reason": "could not fetch folder metadata"
        })
        return

    thesis_name = folder_meta["name"]

    # Match to scan — exact first, then case-insensitive
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
            return
        thesis_name = matched  # use the scan key casing

    # Build filename → shareable link
    links = {
        f["name"]: f"https://drive.google.com/file/d/{f['id']}/view"
        for f in files
    }

    scan[thesis_name]["drive_links"] = links
    scan[thesis_name]["drive_links_registered_at"] = datetime.utcnow().isoformat()
    scan[thesis_name]["drive_folder_id"] = folder_id

    registered.append({
        "thesis_name": thesis_name,
        "drive_folder_id": folder_id,
        "files_registered": len(links),
    })


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

    scan[thesis_name]["drive_links"] = {}
    scan[thesis_name]["drive_links_registered_at"] = None
    scan[thesis_name]["drive_folder_id"] = None
    _write_scan(scan)

    return {"deleted": True, "thesis_name": thesis_name}


# ── Drive API helpers ──────────────────────────────────────────────────────────

def _get_folder_metadata(service, folder_id: str) -> dict | None:
    """Returns {id, name} for a single folder. None on error."""
    try:
        result = service.files().get(
            fileId=folder_id,
            fields="id, name",
        ).execute()
        return result
    except Exception:
        return None


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

    try:
        return build("drive", "v3", developerKey=api_key)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"API key auth failed: {e}. Check GOOGLE_DRIVE_API_KEY value."
        )