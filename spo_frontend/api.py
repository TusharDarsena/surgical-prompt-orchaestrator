"""
API client for SPO backend.
All HTTP calls go through here — pages never call requests directly.
BASE_URL can be overridden with SPO_API_URL env var.
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

def health():
    try:
        return requests.get(_url("/health"), timeout=3).json()
    except Exception:
        return None


def import_status():
    return _handle(requests.get(_url("/import/status")))


# ── Synopsis ───────────────────────────────────────────────────────────────────

def get_synopsis():
    r = requests.get(_url("/thesis/synopsis"))
    if r.status_code == 404:
        return None
    return _handle(r)


def save_synopsis(data: dict):
    existing = get_synopsis()
    if existing:
        return _handle(requests.patch(_url("/thesis/synopsis"), json=data))
    return _handle(requests.post(_url("/thesis/synopsis"), json=data))


# ── Chapters ───────────────────────────────────────────────────────────────────

def list_chapters():
    return _handle(requests.get(_url("/thesis/chapters"))) or []


def get_chapter(chapter_id: str):
    return _handle(requests.get(_url(f"/thesis/chapters/{chapter_id}")))


def create_chapter(data: dict):
    return _handle(requests.post(_url("/thesis/chapters"), json=data))


def update_chapter(chapter_id: str, data: dict):
    return _handle(requests.patch(_url(f"/thesis/chapters/{chapter_id}"), json=data))


def delete_chapter(chapter_id: str):
    return _handle(requests.delete(_url(f"/thesis/chapters/{chapter_id}")))


# ── Subtopics ──────────────────────────────────────────────────────────────────

def add_subtopic(chapter_id: str, data: dict):
    return _handle(requests.post(_url(f"/thesis/chapters/{chapter_id}/subtopics"), json=data))


def update_subtopic(chapter_id: str, subtopic_id: str, data: dict):
    return _handle(requests.patch(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}"), json=data
    ))


def delete_subtopic(chapter_id: str, subtopic_id: str):
    return _handle(requests.delete(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}")
    ))


def get_suggested_sources(chapter_id: str, subtopic_id: str):
    return _handle(requests.get(
        _url(f"/thesis/chapters/{chapter_id}/subtopics/{subtopic_id}/suggested-sources")
    )) or {}


# ── Source Groups ──────────────────────────────────────────────────────────────

def list_source_groups():
    return _handle(requests.get(_url("/sources/groups"))) or []


def get_source_group(group_id: str):
    return _handle(requests.get(_url(f"/sources/groups/{group_id}")))


def create_source_group(data: dict):
    return _handle(requests.post(_url("/sources/groups"), json=data))


def delete_source_group(group_id: str):
    return _handle(requests.delete(_url(f"/sources/groups/{group_id}")))


# ── Sources ────────────────────────────────────────────────────────────────────

def list_sources(group_id: str):
    return _handle(requests.get(_url(f"/sources/groups/{group_id}/sources"))) or []


def create_source(group_id: str, data: dict):
    return _handle(requests.post(_url(f"/sources/groups/{group_id}/sources"), json=data))


def delete_source(group_id: str, source_id: str):
    return _handle(requests.delete(_url(f"/sources/groups/{group_id}/sources/{source_id}")))


# ── Index Cards ────────────────────────────────────────────────────────────────

def get_index_card(group_id: str, source_id: str):
    r = requests.get(_url(f"/sources/groups/{group_id}/sources/{source_id}/index-card"))
    if r.status_code == 404:
        return None
    return _handle(r)


def save_index_card(group_id: str, source_id: str, data: dict, exists: bool):
    url = _url(f"/sources/groups/{group_id}/sources/{source_id}/index-card")
    if exists:
        return _handle(requests.patch(url, json=data))
    return _handle(requests.post(url, json=data))


def delete_index_card(group_id: str, source_id: str):
    return _handle(requests.delete(
        _url(f"/sources/groups/{group_id}/sources/{source_id}/index-card")
    ))


# ── Notes ──────────────────────────────────────────────────────────────────────

def list_notes(scope: str, entity_id: str):
    return (_handle(requests.get(_url(f"/notes/{scope}/{entity_id}"))) or {}).get("notes", [])


def create_note(scope: str, entity_id: str, data: dict):
    return _handle(requests.post(_url(f"/notes/{scope}/{entity_id}"), json=data))


def update_note(scope: str, entity_id: str, note_id: str, data: dict):
    return _handle(requests.patch(_url(f"/notes/{scope}/{entity_id}/{note_id}"), json=data))


def delete_note(scope: str, entity_id: str, note_id: str):
    return _handle(requests.delete(_url(f"/notes/{scope}/{entity_id}/{note_id}")))


# ── Task Blueprints ────────────────────────────────────────────────────────────

def get_task_blueprint(chapter_id: str, subtopic_id: str):
    r = requests.get(_url(f"/tasks/{chapter_id}/{subtopic_id}"))
    if r.status_code == 404:
        return None
    return _handle(r)


def save_task_blueprint(chapter_id: str, subtopic_id: str, data: dict):
    return _handle(requests.post(_url(f"/tasks/{chapter_id}/{subtopic_id}"), json=data))


def delete_task_blueprint(chapter_id: str, subtopic_id: str):
    return _handle(requests.delete(_url(f"/tasks/{chapter_id}/{subtopic_id}")))


# ── Consistency Chain ──────────────────────────────────────────────────────────

def get_chapter_chain(chapter_id: str):
    return (_handle(requests.get(_url(f"/consistency/{chapter_id}"))) or {}).get("chain", [])


def save_consistency_summary(chapter_id: str, subtopic_id: str, data: dict):
    return _handle(requests.post(_url(f"/consistency/{chapter_id}/{subtopic_id}"), json=data))


def get_previous_summary(chapter_id: str, subtopic_id: str):
    return _handle(requests.get(
        _url(f"/consistency/{chapter_id}/previous-for/{subtopic_id}")
    )) or {}


def delete_consistency_summary(chapter_id: str, subtopic_id: str):
    return _handle(requests.delete(_url(f"/consistency/{chapter_id}/{subtopic_id}")))


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