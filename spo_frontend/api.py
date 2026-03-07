"""

API client for SPO backend.
All HTTP calls go through here — pages never call requests directly.
BASE_URL can be overridden with SPO_API_URL env var.

Caching strategy (single-user local app):
  - All read-only functions are decorated with @st.cache_data (no TTL).
  - Every mutation function clears only the specific cache entry it affects,
    using function.clear(*args) for per-argument precision.
    Do NOT add a TTL — that would create a second source of truth.
"""

import os
import requests
import streamlit as st

BASE_URL = os.environ.get("SPO_API_URL", "http://localhost:8000")


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _handle(resp: requests.Response) -> dict | list | None:
    try:
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        st.error(f"API error {resp.status_code}: {detail}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def post(path: str, data: dict):
    """Generic POST — used by JSON import endpoints."""
    return _handle(requests.post(_url(path), json=data))


def import_chapterization(chapter_id: str, data: dict):
    """POST /import/chapterization/{chapter_id} with cache clearing."""
    result = _handle(requests.post(_url(f"/import/chapterization/{chapter_id}"), json=data))
    if result is not None:
        list_chapters.clear()
    return result


def import_chapterization_bulk(data: list):
    """POST /import/chapterization/bulk — multiple chapters in one upload."""
    result = _handle(requests.post(_url("/import/chapterization/bulk"), json=data))
    if result is not None:
        list_chapters.clear()
    return result


# ── Health ─────────────────────────────────────────────────────────────────────

@st.cache_data
def health():
    try:
        return requests.get(_url("/health"), timeout=3).json()
    except Exception:
        return None


@st.cache_data
def import_status():
    return _handle(requests.get(_url("/import/status")))


# ── Synopsis ───────────────────────────────────────────────────────────────────

@st.cache_data
def get_synopsis():
    r = requests.get(_url("/thesis/synopsis"))
    if r.status_code == 404:
        return None
    return _handle(r)


def save_synopsis(data: dict):
    """PUT upsert — backend decides create vs update. No prior GET needed."""
    result = _handle(requests.put(_url("/thesis/synopsis"), json=data))
    if result is not None:
        get_synopsis.clear()
    return result


# ── Chapters ───────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def list_chapters():
    return _handle(requests.get(_url("/thesis/chapters"))) or []


@st.cache_data(show_spinner=False)
def get_chapter(chapter_id: str):
    return _handle(requests.get(_url(f"/thesis/chapters/{chapter_id}")))


def create_chapter(data: dict):
    result = _handle(requests.post(_url("/thesis/chapters"), json=data))
    if result is not None:
        list_chapters.clear()
    return result


def update_chapter(chapter_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/thesis/chapters/{chapter_id}"), json=data))
    if result is not None:
        get_chapter.clear(chapter_id)
        list_chapters.clear()
    return result


def delete_chapter(chapter_id: str):
    result = _handle(requests.delete(_url(f"/thesis/chapters/{chapter_id}")))
    if result is not None:
        get_chapter.clear(chapter_id)
        list_chapters.clear()
    return result


# ── Subtopics ──────────────────────────────────────────────────────────────────

def add_subtopic(chapter_id: str, data: dict):
    result = _handle(requests.post(_url(f"/thesis/chapters/{chapter_id}/subtopics"), json=data))
    if result is not None:
        get_chapter.clear(chapter_id)
        list_chapters.clear()
    return result


def update_subtopic(chapter_id: str, subtopic_id: str, data: dict):
    result = _handle(requests.patch(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}"), json=data
    ))
    if result is not None:
        get_chapter.clear(chapter_id)
        list_chapters.clear()
    return result


def delete_subtopic(chapter_id: str, subtopic_id: str):
    result = _handle(requests.delete(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}")
    ))
    if result is not None:
        get_chapter.clear(chapter_id)
        list_chapters.clear()
    return result


@st.cache_data
def get_suggested_sources(chapter_id: str, subtopic_id: str):
    return _handle(requests.get(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}/suggested-sources")
    )) or {}


# ── Source Groups ──────────────────────────────────────────────────────────────

@st.cache_data
def list_source_groups():
    return _handle(requests.get(_url("/sources/groups"))) or []

@st.cache_data
def get_library_view():
    """
    Fetches the entire library (groups, sources, embedded index cards, notes)
    in one API call to avoid N+1 queries.
    """
    return _handle(requests.get(_url("/sources/library-view"))) or {"groups": [], "notes": {"source": {}, "source_group": {}}}


@st.cache_data
def get_source_group(group_id: str):
    return _handle(requests.get(_url(f"/sources/groups/{group_id}")))


def create_source_group(data: dict):
    result = _handle(requests.post(_url("/sources/groups"), json=data))
    if result is not None:
        list_source_groups.clear()
        get_library_view.clear()
    return result


def update_source_group(group_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/sources/groups/{group_id}"), json=data))
    if result is not None:
        get_source_group.clear(group_id)
        list_source_groups.clear()
        get_library_view.clear()
    return result


def delete_source_group(group_id: str):
    result = _handle(requests.delete(_url(f"/sources/groups/{group_id}")))
    if result is not None:
        get_source_group.clear(group_id)
        list_source_groups.clear()
        get_library_view.clear()
    return result


# ── Sources ────────────────────────────────────────────────────────────────────

@st.cache_data
def list_sources(group_id: str):
    return _handle(requests.get(_url(f"/sources/groups/{group_id}/sources"))) or []


def create_source(group_id: str, data: dict):
    result = _handle(requests.post(_url(f"/sources/groups/{group_id}/sources"), json=data))
    if result is not None:
        list_sources.clear(group_id)
        list_source_groups.clear()  # ready_count may change
        get_library_view.clear()
    return result


def update_source(group_id: str, source_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/sources/groups/{group_id}/sources/{source_id}"), json=data))
    if result is not None:
        list_sources.clear(group_id)
        get_library_view.clear()
    return result


def delete_source(group_id: str, source_id: str):
    result = _handle(requests.delete(_url(f"/sources/groups/{group_id}/sources/{source_id}")))
    if result is not None:
        list_sources.clear(group_id)
        list_source_groups.clear()
        get_library_view.clear()
    return result


def import_source(data: dict):
    """POST /import/source — creates group + all sources + index cards from source.json in one call."""
    result = _handle(requests.post(_url("/import/source"), json=data))
    if result is not None:
        list_source_groups.clear()  # a new group was created
        get_library_view.clear()
    return result


# ── Index Cards ────────────────────────────────────────────────────────────────

@st.cache_data
def get_index_card(group_id: str, source_id: str):
    r = requests.get(_url(f"/sources/groups/{group_id}/sources/{source_id}/index-card"))
    if r.status_code == 404:
        return None
    return _handle(r)


def save_index_card(group_id: str, source_id: str, data: dict, exists: bool):
    url = _url(f"/sources/groups/{group_id}/sources/{source_id}/index-card")
    result = _handle(requests.patch(url, json=data) if exists else requests.post(url, json=data))
    if result is not None:
        get_index_card.clear(group_id, source_id)
        list_sources.clear(group_id)       # has_index_card flag on source
        list_source_groups.clear()         # ready_count summary
        get_library_view.clear()
    return result


def delete_index_card(group_id: str, source_id: str):
    result = _handle(requests.delete(
        _url(f"/sources/groups/{group_id}/sources/{source_id}/index-card")
    ))
    if result is not None:
        get_index_card.clear(group_id, source_id)
        list_sources.clear(group_id)
        list_source_groups.clear()
        get_library_view.clear()
    return result


# ── Notes ──────────────────────────────────────────────────────────────────────

@st.cache_data
def list_notes(scope: str, entity_id: str):
    return (_handle(requests.get(_url(f"/notes/{scope}/{entity_id}"))) or {}).get("notes", [])


def create_note(scope: str, entity_id: str, data: dict):
    result = _handle(requests.post(_url(f"/notes/{scope}/{entity_id}"), json=data))
    if result is not None:
        list_notes.clear(scope, entity_id)
        get_library_view.clear()
    return result


def update_note(scope: str, entity_id: str, note_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/notes/{scope}/{entity_id}/{note_id}"), json=data))
    if result is not None:
        list_notes.clear(scope, entity_id)
        get_library_view.clear()
    return result


def delete_note(scope: str, entity_id: str, note_id: str):
    result = _handle(requests.delete(_url(f"/notes/{scope}/{entity_id}/{note_id}")))
    if result is not None:
        list_notes.clear(scope, entity_id)
        get_library_view.clear()
    return result


# ── Consistency Chain ──────────────────────────────────────────────────────────

@st.cache_data
def get_chapter_chain(chapter_id: str):
    return (_handle(requests.get(_url(f"/consistency/{chapter_id}"))) or {}).get("chain", [])


def save_consistency_summary(chapter_id: str, subtopic_id: str, data: dict):
    result = _handle(requests.post(_url(f"/consistency/{chapter_id}/{subtopic_id}"), json=data))
    if result is not None:
        get_chapter_chain.clear(chapter_id)
        get_previous_summary.clear(chapter_id, subtopic_id)
    return result


@st.cache_data
def get_previous_summary(chapter_id: str, subtopic_id: str):
    return _handle(requests.get(
        _url(f"/consistency/{chapter_id}/previous-for/{subtopic_id}")
    )) or {}


def delete_consistency_summary(chapter_id: str, subtopic_id: str):
    result = _handle(requests.delete(_url(f"/consistency/{chapter_id}/{subtopic_id}")))
    if result is not None:
        get_chapter_chain.clear(chapter_id)
        get_previous_summary.clear(chapter_id, subtopic_id)
    return result


# ── Drive Scanner ──────────────────────────────────────────────────────────────

def scan_local_folder(root_path: str) -> dict | None:
    """
    POST /drive/scan-local
    Scans the given parent folder path and builds the thesis file tree.
    On rescan, adds new folders without touching existing ones.
    """
    try:
        r = requests.post(f"{BASE_URL}/drive/scan-local", json={"root_path": root_path})
        if r.status_code == 200:
            return r.json()
        st.error(f"Scan failed: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def get_local_files() -> dict | None:
    """
    GET /drive/local-files
    Returns the stored thesis file tree with import status per thesis.
    Returns None if nothing has been scanned yet (not an error).
    """
    try:
        r = requests.get(f"{BASE_URL}/drive/local-files")
        if r.status_code == 200:
            return r.json()
        # 404 just means no scan has been run yet — treat as empty, not error
        if r.status_code == 404:
            return {"thesis_folders": [], "count": 0}
        st.error(f"Could not load file tree: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def save_index_card_json(thesis_name: str, level2_path: str, json_text: str) -> dict | None:
    """
    POST /drive/save-index-card
    Saves the pasted NotebookLM JSON to disk and auto-imports it to SPO.
    Returns result dict with saved/imported status and error details if any.
    """
    try:
        r = requests.post(f"{BASE_URL}/drive/save-index-card", json={
            "thesis_name": thesis_name,
            "level2_path": level2_path,
            "json_text": json_text,
        })
        if r.status_code == 200:
            return r.json()
        st.error(f"Save failed: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None

# ── Drive Links ────────────────────────────────────────────────────────────────


def register_drive_links(drive_parent_folder_id: str) -> dict | None:
    """
    POST /drive/register-links
    Walks the Drive parent folder (4 levels deep, mirroring local structure)
    and registers shareable links for ALL thesis folders in one call.
    Call once after uploading all thesis folders to Drive.
    """
    try:
        r = requests.post(f"{BASE_URL}/drive/register-links", json={
            "drive_parent_folder_id": drive_parent_folder_id,
        })
        if r.status_code == 200:
            return r.json()
        st.error(f"Drive registration failed: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def get_drive_links(thesis_name: str) -> dict | None:
    """
    GET /drive/links/{thesis_name}
    Returns stored Drive links for a thesis as { filename: link }.
    Returns None silently if not registered — not an error.
    """
    try:
        r = requests.get(f"{BASE_URL}/drive/links/{thesis_name}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        st.error(f"Could not load Drive links: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


# ── Compiler ───────────────────────────────────────────────────────────────────


def compile_notebooklm_prompt(
    chapter_id: str,
    subtopic_id: str,
    word_count: int | None = None,
    style_notes: str | None = None,
) -> dict | None:
    """
    GET /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}
    Builds prompt directly from chapterization data.
    Returns prompt + meta.required_sources with resolved filenames/links.
    """
    try:
        params = {}
        if word_count:
            params["word_count"] = word_count
        if style_notes:
            params["academic_style_notes"] = style_notes
        r = requests.get(
            f"{BASE_URL}/compile/notebooklm-prompt/{chapter_id}/{subtopic_id}",
            params=params
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Compile failed: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


# ── Section Drafts ─────────────────────────────────────────────────────────────


def get_section_draft(chapter_id: str, subtopic_id: str) -> dict | None:
    """
    GET /sections/{chapter_id}/{subtopic_id}/draft
    Returns the saved draft for a subtopic, or None if none exists.
    """
    try:
        r = requests.get(f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        st.error(f"Could not load draft: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def save_section_draft(chapter_id: str, subtopic_id: str, text: str) -> dict | None:
    """
    POST /sections/{chapter_id}/{subtopic_id}/draft
    Saves or overwrites the draft for a subtopic.
    """
    try:
        r = requests.post(
            f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft",
            json={"text": text}
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Could not save draft: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def delete_section_draft(chapter_id: str, subtopic_id: str) -> bool:
    """
    DELETE /sections/{chapter_id}/{subtopic_id}/draft
    """
    try:
        r = requests.delete(f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft")
        return r.status_code == 200
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return False