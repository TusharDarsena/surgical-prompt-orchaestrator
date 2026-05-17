"""
Google Docs Service
-------------------
Handles all Google Docs interactions for SPO: OAuth 2.0 flow,
document creation, and smart subtopic upserts.

Key design decisions (see implementation_plan.md for full context):
  - Web OAuth flow (not InstalledAppFlow) so the same code works
    locally and on a deployed VPS. Set GDOCS_REDIRECT_URI env var
    for non-localhost deployments.
  - Token stored in OS keychain (keyring) with plaintext fallback.
  - Named Range insert/delete ordering: INSERT first (at old start),
    then DELETE the now-shifted old content. Reversing this corrupts sync.
  - Conflict detection uses normalized string comparison, NOT SHA-256.
    Google Docs normalizes whitespace and control chars, so hashes
    false-positive constantly.
  - Chapter doc creation protected by asyncio.Lock per chapter_id
    to prevent race conditions in batch exports.

Exception contract (router must handle):
  GDocsNotConfiguredError  → 503
  GDocsAuthError           → 401
  GDocsConflictError       → 409  (contains gdoc_excerpt + spo_excerpt)
  All others propagate     → 500
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from services import storage

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

CLIENT_SECRET_FILE = os.environ.get(
    "GDOCS_CLIENT_SECRET_FILE",
    os.path.join(os.path.dirname(__file__), "..", "..", "service-account.json"),
)
CLIENT_SECRET_FILE = os.path.normpath(CLIENT_SECRET_FILE)

REDIRECT_URI = os.environ.get(
    "GDOCS_REDIRECT_URI",
    "http://localhost:8000/gdocs/auth/callback",
)

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

KEYRING_SERVICE = "spo"
KEYRING_KEY = "google_oauth_token"
MISC_TOKEN_KEY = "gdocs_token"
MISC_STATE_KEY = "gdocs_oauth_state"

# ── Domain exceptions ──────────────────────────────────────────────────────────


class GDocsNotConfiguredError(Exception):
    """Client secret file is missing or misconfigured."""


class GDocsAuthError(Exception):
    """OAuth token missing, expired, or invalid."""


class GDocsConflictError(Exception):
    """Manual edits detected in Google Docs — safe sync guard fired."""

    def __init__(self, gdoc_excerpt: str, spo_excerpt: str, last_export_at: Optional[str]):
        self.gdoc_excerpt = gdoc_excerpt
        self.spo_excerpt = spo_excerpt
        self.last_export_at = last_export_at
        super().__init__("Manual edits detected in Google Docs")


# ── Token storage (keyring → plaintext fallback) ───────────────────────────────


def _save_token(token_json: str) -> None:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_KEY, token_json)
        logger.debug("OAuth token saved to system keychain.")
        return
    except Exception:
        logger.warning(
            "keyring unavailable — storing OAuth token in plaintext JSON. "
            "Do not commit spo_data/ to version control."
        )
    try:
        storage.write_misc(MISC_TOKEN_KEY, json.loads(token_json), thesis_id="")
    except Exception as e:
        logger.error("Failed to write token to storage: %s", e)


def _load_token() -> Optional[str]:
    try:
        import keyring
        val = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
        if val:
            return val
    except Exception:
        pass
    data = storage.read_misc(MISC_TOKEN_KEY, thesis_id="")
    return json.dumps(data) if data else None


# ── Credential lifecycle ───────────────────────────────────────────────────────


def _load_and_refresh_credentials():
    """
    Load stored credentials and refresh if expired.
    Raises GDocsAuthError if no token is stored yet.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_json = _load_token()
    if not token_json:
        raise GDocsAuthError(
            "No Google credentials found. Visit /gdocs/auth to connect your account."
        )

    try:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    except Exception as e:
        raise GDocsAuthError(f"Stored credentials are corrupt: {e}. Re-authenticate at /gdocs/auth.")

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds.to_json())
        except Exception as e:
            raise GDocsAuthError(f"Failed to refresh credentials: {e}. Re-authenticate at /gdocs/auth.")

    return creds


@asynccontextmanager
async def _gdocs_client():
    """
    Async context manager that yields an authenticated Google Docs service object.
    Mirrors the _nlm_client() pattern from notebooklm_service.py.
    Credential refresh runs in a thread to avoid blocking the event loop.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise GDocsNotConfiguredError(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib"
        )

    creds = await asyncio.to_thread(_load_and_refresh_credentials)
    service = build("docs", "v1", credentials=creds)
    yield service


# ── OAuth flow ─────────────────────────────────────────────────────────────────


def get_auth_url() -> str:
    """
    Initiates the OAuth 2.0 web flow. Returns the URL the user must visit.
    Saves the `state` parameter to misc storage for CSRF validation.
    """
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise GDocsNotConfiguredError(
            "google-auth-oauthlib not installed. "
            "Run: pip install google-auth-oauthlib"
        )

    if not os.path.exists(CLIENT_SECRET_FILE):
        raise GDocsNotConfiguredError(
            f"Client secret file not found at: {CLIENT_SECRET_FILE}. "
            "Set GDOCS_CLIENT_SECRET_FILE env var to the correct path."
        )

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")
    storage.write_misc(MISC_STATE_KEY, {"state": state}, thesis_id="")
    logger.info("OAuth flow initiated. Redirect URI: %s", REDIRECT_URI)
    return auth_url


def complete_auth_flow(code: str, state: str) -> None:
    """
    Exchanges the authorization code for credentials and saves the token.
    Validates the state parameter to prevent CSRF attacks.
    """
    from google_auth_oauthlib.flow import Flow

    stored = storage.read_misc(MISC_STATE_KEY, thesis_id="")
    if not stored or stored.get("state") != state:
        raise GDocsAuthError("OAuth state mismatch. Possible CSRF attack. Restart the auth flow.")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI, state=state
    )
    flow.fetch_token(code=code)
    _save_token(flow.credentials.to_json())
    logger.info("OAuth flow complete. Token saved.")


def is_connected() -> bool:
    """Returns True if a valid (or refreshable) token exists."""
    try:
        _load_and_refresh_credentials()
        return True
    except GDocsAuthError:
        return False


# ── Chapter-level doc creation lock ───────────────────────────────────────────
# Prevents race conditions when two batch workers export different subtopics
# from the same chapter simultaneously. Mirrors _run_locks in notebooklm_service.py.

_chapter_doc_locks: dict[str, asyncio.Lock] = {}
_chapter_locks_mutex = asyncio.Lock()


async def _get_chapter_doc_lock(chapter_id: str) -> asyncio.Lock:
    async with _chapter_locks_mutex:
        if chapter_id not in _chapter_doc_locks:
            _chapter_doc_locks[chapter_id] = asyncio.Lock()
        return _chapter_doc_locks[chapter_id]


async def get_or_create_chapter_doc(
    thesis_id: str,
    chapter_id: str,
    chapter_title: str,
) -> str:
    """
    Returns the gdoc_id for the chapter. Creates the Google Doc if it doesn't
    exist yet. The creation lock ensures only one worker creates the doc even
    when multiple subtopics are exported concurrently.
    """
    lock = await _get_chapter_doc_lock(chapter_id)
    async with lock:
        chapter = storage.read_chapter(chapter_id, thesis_id)
        if not chapter:
            raise ValueError(f"Chapter '{chapter_id}' not found in storage.")

        existing_gdoc_id = chapter.get("gdoc_id")
        if existing_gdoc_id:
            return existing_gdoc_id

        # Create the Google Doc
        async with _gdocs_client() as docs:
            doc = await asyncio.to_thread(
                lambda: docs.documents()
                .create(body={"title": chapter_title})
                .execute()
            )
        gdoc_id = doc["documentId"]
        logger.info("Created Google Doc '%s' (ID: %s) for chapter %s", chapter_title, gdoc_id, chapter_id)

        # Read-merge-write to avoid clobbering other chapter keys
        chapter["gdoc_id"] = gdoc_id
        chapter["gdoc_created_at"] = datetime.now(timezone.utc).isoformat()
        storage.write_chapter(chapter_id, chapter, thesis_id)
        return gdoc_id


# ── Text normalization for conflict detection ──────────────────────────────────


def _normalize(text: str) -> str:
    """
    Strips Google Docs control characters and collapses whitespace.
    SHA-256 on raw Docs text false-positives constantly due to \x0b (line break)
    vs \n normalization. Comparing normalized strings is both simpler and correct.
    """
    text = text.replace("\x0b", "\n").replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    return " ".join(text.split()).strip()



def _get_utf16_length(text: str) -> int:
    """
    Calculates the length of a string in UTF-16 code units.
    Essential for Google Docs API indexing, where surrogate pairs 
    (emojis, complex math symbols) count as 2 units instead of 1.
    """
    return len(text.encode('utf-16-le')) // 2


# ── Core export logic ──────────────────────────────────────────────────────────


def _read_named_range_text(docs_service, doc_id: str, named_range_id: str) -> Optional[str]:
    """
    Reads the text content of a named range from the document.
    Returns None if the range no longer exists (e.g. user deleted the boundary).
    """
    doc = docs_service.documents().get(documentId=doc_id).execute()
    named_ranges = doc.get("namedRanges", {})

    # Find this range across all named range entries
    for _name, ranges in named_ranges.items():
        for r in ranges.get("namedRanges", []):
            if r.get("namedRangeId") == named_range_id:
                segments = r.get("ranges", [])
                if not segments:
                    return None
                start = segments[0]["startIndex"]
                end = segments[-1]["endIndex"]
                # Extract text from document content
                content = doc.get("body", {}).get("content", [])
                text = _extract_text(content, start, end)
                return text

    return None  # named range was deleted


def _extract_text(content: list, start: int, end: int) -> str:
    """Extract plain text from document content within [start, end) index range."""
    chars = []
    for element in content:
        for run in element.get("paragraph", {}).get("elements", []):
            run_start = run.get("startIndex", 0)
            run_end = run.get("endIndex", 0)
            if run_end <= start or run_start >= end:
                continue
            text_run = run.get("textRun", {})
            text = text_run.get("content", "")
            # Clip to our range
            clip_start = max(0, start - run_start)
            clip_end = min(len(text), end - run_start)
            chars.append(text[clip_start:clip_end])
    return "".join(chars)


def _get_document_end_index(docs_service, doc_id: str) -> int:
    """Returns the index of the last character in the document body."""
    doc = docs_service.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    if not content:
        return 1
    return content[-1].get("endIndex", 1)


def _build_insert_requests(text: str, index: int, heading_text: str, heading_index: int) -> list:
    """
    Build batchUpdate requests to insert heading + body text at the given index.
    Returns a list of request dicts for a single documents().batchUpdate() call.
    Order: insertText first, then updateParagraphStyle.
    """
    full_text = f"{heading_text}\n{text}\n"
    heading_end = heading_index + len(heading_text) + 1

    return [
        # 1. Insert all text at once
        {
            "insertText": {
                "location": {"index": index},
                "text": full_text,
            }
        },
        # 2. Apply Heading 2 to the heading line
        {
            "updateParagraphStyle": {
                "range": {"startIndex": heading_index, "endIndex": heading_end},
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType",
            }
        },
    ]


async def export_subtopic(
    thesis_id: str,
    chapter_id: str,
    chapter_title: str,
    subtopic_id: str,
    subtopic_title: str,
    draft_text: str,
    force: bool = False,
) -> dict:
    """
    Main export function. Upserts a subtopic section into the chapter's Google Doc.

    Behavior:
    - If subtopic has never been exported → append to end of doc.
    - If subtopic was exported before and text in Docs matches last export → overwrite.
    - If text in Docs differs from last export and force=False → raise GDocsConflictError.
    - If named range was deleted → log, re-append, show warning to user.

    Returns a dict with doc_url and any warnings.
    """
    gdoc_id = await get_or_create_chapter_doc(thesis_id, chapter_id, chapter_title)

    chapter = storage.read_chapter(chapter_id, thesis_id)
    subtopics = chapter.get("subtopics", [])
    subtopic_meta = next((s for s in subtopics if s.get("subtopic_id") == subtopic_id), None)
    if subtopic_meta is None:
        raise ValueError(f"Subtopic '{subtopic_id}' not found in chapter '{chapter_id}'.")

    named_range_id: Optional[str] = subtopic_meta.get("gdoc_named_range_id")
    last_normalized: Optional[str] = subtopic_meta.get("last_gdoc_export_normalized")
    last_export_at: Optional[str] = subtopic_meta.get("last_gdoc_export_at")

    warning: Optional[str] = None

    async with _gdocs_client() as docs:
        if named_range_id:
            # ── Existing export: read current Docs text ────────────────────────
            current_text = await asyncio.to_thread(
                _read_named_range_text, docs, gdoc_id, named_range_id
            )

            if current_text is None:
                # Named range was deleted — fall back to fresh append
                logger.warning(
                    "Named range %s missing for subtopic %s — re-appending.",
                    named_range_id, subtopic_id,
                )
                warning = "named_range_missing"
                named_range_id = None

            elif not force:
                # ── Safe Sync Guard ────────────────────────────────────────────
                normalized_current = _normalize(current_text)
                if normalized_current != (last_normalized or ""):
                    raise GDocsConflictError(
                        gdoc_excerpt=current_text[:300],
                        spo_excerpt=draft_text[:300],
                        last_export_at=last_export_at,
                    )

        if named_range_id:
            # ── Update existing range ──────────────────────────────────────────
            # Critical ordering: INSERT new text FIRST, then DELETE old (shifted) content.
            doc = await asyncio.to_thread(
                lambda: docs.documents().get(documentId=gdoc_id).execute()
            )
            named_ranges_map = doc.get("namedRanges", {})
            range_segments = None
            for _name, entry in named_ranges_map.items():
                for r in entry.get("namedRanges", []):
                    if r.get("namedRangeId") == named_range_id:
                        range_segments = r.get("ranges", [])
                        break

            if range_segments:
                old_start = range_segments[0]["startIndex"]
                old_end = range_segments[-1]["endIndex"]
                old_length = old_end - old_start
                new_full_text = f"{subtopic_title}\n{draft_text}\n"
                new_length = _get_utf16_length(new_full_text)
                heading_length = _get_utf16_length(subtopic_title)

                requests = [
                    # Step 1: Insert new text at old_start
                    {"insertText": {"location": {"index": old_start}, "text": new_full_text}},
                    # Step 2: Apply Heading 2 to the heading line (now at old_start)
                    {
                        "updateParagraphStyle": {
                            "range": {
                                "startIndex": old_start,
                                "endIndex": old_start + heading_length + 1,
                            },
                            "paragraphStyle": {"namedStyleType": "HEADING_2"},
                            "fields": "namedStyleType",
                        }
                    },
                    # Step 3: Delete old content (shifted by new_length)
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": old_start + new_length,
                                "endIndex": old_start + new_length + old_length,
                            }
                        }
                    },
                ]
                await asyncio.to_thread(
                    lambda: docs.documents()
                    .batchUpdate(documentId=gdoc_id, body={"requests": requests})
                    .execute()
                )
                logger.info("Updated subtopic %s in doc %s.", subtopic_id, gdoc_id)
            else:
                # Couldn't find range segments despite having ID — treat as new
                warning = "named_range_missing"
                named_range_id = None

        if not named_range_id:
            # ── Fresh append ───────────────────────────────────────────────────
            doc_end = await asyncio.to_thread(_get_document_end_index, docs, gdoc_id)
            # Insert before the last index (which is a trailing newline/paragraph)
            insert_at = max(1, doc_end - 1)
            full_text = f"{subtopic_title}\n{draft_text}\n"
            heading_length = _get_utf16_length(subtopic_title)
            heading_end = insert_at + heading_length + 1
            new_length = _get_utf16_length(full_text)

            requests = [
                {"insertText": {"location": {"index": insert_at}, "text": full_text}},
                {
                    "updateParagraphStyle": {
                        "range": {"startIndex": insert_at, "endIndex": heading_end},
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                        "fields": "namedStyleType",
                    }
                },
            ]
            await asyncio.to_thread(
                lambda: docs.documents()
                .batchUpdate(documentId=gdoc_id, body={"requests": requests})
                .execute()
            )
            logger.info("Appended subtopic %s to doc %s.", subtopic_id, gdoc_id)

            # Create a named range for the inserted content
            new_end = insert_at + new_length
            range_name = f"spo_{subtopic_id}"
            result = await asyncio.to_thread(
                lambda: docs.documents()
                .batchUpdate(
                    documentId=gdoc_id,
                    body={
                        "requests": [
                            {
                                "createNamedRange": {
                                    "name": range_name,
                                    "range": {"startIndex": insert_at, "endIndex": new_end},
                                }
                            }
                        ]
                    },
                )
                .execute()
            )
            replies = result.get("replies", [{}])
            named_range_id = replies[0].get("createNamedRange", {}).get("namedRangeId")

    # ── Persist subtopic metadata (read-merge-write) ───────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    chapter = storage.read_chapter(chapter_id, thesis_id)
    for sub in chapter.get("subtopics", []):
        if sub.get("subtopic_id") == subtopic_id:
            sub["gdoc_named_range_id"] = named_range_id
            sub["last_gdoc_export_normalized"] = _normalize(draft_text)
            sub["last_gdoc_export_at"] = now
            sub["last_gdoc_export_status"] = "success" if not warning else warning
            break
    storage.write_chapter(chapter_id, chapter, thesis_id)

    return {
        "doc_url": f"https://docs.google.com/document/d/{gdoc_id}/edit",
        "gdoc_id": gdoc_id,
        "named_range_id": named_range_id,
        "warning": warning,
        "exported_at": now,
    }
