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

@st.cache_data
def list_chapters():
    return _handle(requests.get(_url("/thesis/chapters"))) or []


@st.cache_data
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
def get_source_group(group_id: str):
    return _handle(requests.get(_url(f"/sources/groups/{group_id}")))


def create_source_group(data: dict):
    result = _handle(requests.post(_url("/sources/groups"), json=data))
    if result is not None:
        list_source_groups.clear()
    return result


def update_source_group(group_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/sources/groups/{group_id}"), json=data))
    if result is not None:
        get_source_group.clear(group_id)
        list_source_groups.clear()
    return result


def delete_source_group(group_id: str):
    result = _handle(requests.delete(_url(f"/sources/groups/{group_id}")))
    if result is not None:
        get_source_group.clear(group_id)
        list_source_groups.clear()
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
    return result


def update_source(group_id: str, source_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/sources/groups/{group_id}/sources/{source_id}"), json=data))
    if result is not None:
        list_sources.clear(group_id)
    return result


def delete_source(group_id: str, source_id: str):
    result = _handle(requests.delete(_url(f"/sources/groups/{group_id}/sources/{source_id}")))
    if result is not None:
        list_sources.clear(group_id)
        list_source_groups.clear()
    return result


def import_source(data: dict):
    """POST /import/source — creates group + all sources + index cards from source.json in one call."""
    result = _handle(requests.post(_url("/import/source"), json=data))
    if result is not None:
        list_source_groups.clear()  # a new group was created
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
    return result


def delete_index_card(group_id: str, source_id: str):
    result = _handle(requests.delete(
        _url(f"/sources/groups/{group_id}/sources/{source_id}/index-card")
    ))
    if result is not None:
        get_index_card.clear(group_id, source_id)
        list_sources.clear(group_id)
        list_source_groups.clear()
    return result


# ── Notes ──────────────────────────────────────────────────────────────────────

@st.cache_data
def list_notes(scope: str, entity_id: str):
    return (_handle(requests.get(_url(f"/notes/{scope}/{entity_id}"))) or {}).get("notes", [])


def create_note(scope: str, entity_id: str, data: dict):
    result = _handle(requests.post(_url(f"/notes/{scope}/{entity_id}"), json=data))
    if result is not None:
        list_notes.clear(scope, entity_id)
    return result


def update_note(scope: str, entity_id: str, note_id: str, data: dict):
    result = _handle(requests.patch(_url(f"/notes/{scope}/{entity_id}/{note_id}"), json=data))
    if result is not None:
        list_notes.clear(scope, entity_id)
    return result


def delete_note(scope: str, entity_id: str, note_id: str):
    result = _handle(requests.delete(_url(f"/notes/{scope}/{entity_id}/{note_id}")))
    if result is not None:
        list_notes.clear(scope, entity_id)
    return result


# ── Task Blueprints ────────────────────────────────────────────────────────────

@st.cache_data
def get_task_blueprint(chapter_id: str, subtopic_id: str):
    r = requests.get(_url(f"/tasks/{chapter_id}/{subtopic_id}"))
    if r.status_code == 404:
        return None
    return _handle(r)


@st.cache_data
def list_task_blueprints():
    """Fetch all saved Task.md blueprints in one round-trip.
    Use this to build lookup sets instead of calling get_task_blueprint() in a loop.
    """
    return _handle(requests.get(_url("/tasks/"))) or {}


def save_task_blueprint(chapter_id: str, subtopic_id: str, data: dict):
    result = _handle(requests.post(_url(f"/tasks/{chapter_id}/{subtopic_id}"), json=data))
    if result is not None:
        get_task_blueprint.clear(chapter_id, subtopic_id)
        list_task_blueprints.clear()
    return result


def delete_task_blueprint(chapter_id: str, subtopic_id: str):
    result = _handle(requests.delete(_url(f"/tasks/{chapter_id}/{subtopic_id}")))
    if result is not None:
        get_task_blueprint.clear(chapter_id, subtopic_id)
        list_task_blueprints.clear()
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


# ── Compiler ───────────────────────────────────────────────────────────────────

def compile_architect_prompt(chapter_id: str, subtopic_id: str, include_previous: bool = True):
    return _handle(requests.get(
        _url(f"/compile/architect-prompt/{chapter_id}/{subtopic_id}"),
        params={"include_previous_section": include_previous}
    ))


def compile_notebooklm_prompt(
    chapter_id: str, subtopic_id: str,
    word_count: int = None, style_notes: str = None
):
    params = {}
    if word_count:
        params["word_count"] = word_count
    if style_notes:
        params["academic_style_notes"] = style_notes
    return _handle(requests.get(
        _url(f"/compile/notebooklm-prompt/{chapter_id}/{subtopic_id}"),
        params=params
    ))