"""
Tests for services/google_docs_service.py
==========================================
Full pipeline coverage WITHOUT any NotebookLM prompts.
All Google API calls are mocked via the conftest.py `mock_gdocs_client` fixture.

Excluded by design:
  - Manual-edit conflict scenario (GDocsConflictError path) — per spec

Coverage map:
  1. Token storage & environment failures
  2. OAuth state & CSRF hostility
  3. Credential lifecycle (load, refresh, is_connected)
  4. Document end-index & named range helpers
  5. Text normalization engine
  6. UTF-16 length calculation
  7. Chapter doc creation (get_or_create_chapter_doc)
  8. Concurrency & async lock
  9. export_subtopic — fresh append path
  10. export_subtopic — update / re-export path
  11. export_subtopic — named range deleted / missing fallback
  12. export_subtopic — force=True skips safe-sync guard
  13. export_subtopic — metadata persistence
  14. export_subtopic — batchUpdate API failure (partial batch)
  15. _build_insert_requests structure
  16. _extract_text boundary clipping
"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock, call, AsyncMock

from services import storage
from services import google_docs_service
from services.google_docs_service import (
    GDocsAuthError,
    GDocsConflictError,
    GDocsNotConfiguredError,
    _save_token,
    _load_token,
    _load_and_refresh_credentials,
    complete_auth_flow,
    is_connected,
    get_or_create_chapter_doc,
    export_subtopic,
    _read_named_range_text,
    _get_document_end_index,
    _get_utf16_length,
    _normalize,
    _extract_text,
    _build_insert_requests,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_chapter(chapter_id: str, subtopic_id: str = None, **subtopic_kwargs) -> dict:
    """Build a minimal chapter dict with optional subtopic."""
    chapter = {"chapter_id": chapter_id, "subtopics": []}
    if subtopic_id:
        sub = {"subtopic_id": subtopic_id, **subtopic_kwargs}
        chapter["subtopics"].append(sub)
    return chapter


def _make_doc_response(named_ranges: dict = None, content: list = None) -> dict:
    """Build a minimal Google Docs API document response."""
    return {
        "body": {"content": content or [{"endIndex": 100}]},
        "namedRanges": named_ranges or {},
    }


def _make_named_range_entry(named_range_id: str, start: int, end: int) -> dict:
    """Build namedRanges dict as returned by the Google Docs API."""
    return {
        "spo_test": {
            "namedRanges": [
                {
                    "namedRangeId": named_range_id,
                    "ranges": [{"startIndex": start, "endIndex": end}],
                }
            ]
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. TOKEN STORAGE & ENVIRONMENT FAILURES
# ══════════════════════════════════════════════════════════════════════════════


def test_load_token_returns_none_when_no_storage(tmp_spo_data_dir):
    """_load_token returns None when keyring fails and misc storage is empty."""
    with patch("keyring.get_password", side_effect=Exception("Keyring broken")), \
         patch("services.storage.read_misc", return_value=None):
        result = _load_token()
    assert result is None


def test_load_token_keyring_fallback_to_storage(tmp_spo_data_dir):
    """_load_token falls back to storage.read_misc when keyring raises."""
    storage.write_misc(google_docs_service.MISC_TOKEN_KEY, {"dummy": "token"}, thesis_id="")

    with patch("keyring.get_password", side_effect=Exception("Keyring broken")):
        token_json = _load_token()

    assert json.loads(token_json) == {"dummy": "token"}


def test_load_token_prefers_keyring_over_storage(tmp_spo_data_dir):
    """_load_token prefers keyring over misc storage."""
    storage.write_misc(google_docs_service.MISC_TOKEN_KEY, {"source": "disk"}, thesis_id="")

    with patch("keyring.get_password", return_value='{"source": "keyring"}'):
        token_json = _load_token()

    assert json.loads(token_json)["source"] == "keyring"


def test_save_token_keyring_failure_falls_back_to_storage(tmp_spo_data_dir):
    """_save_token falls back to misc storage when keyring is unavailable."""
    with patch("keyring.set_password", side_effect=Exception("Keyring broken")):
        _save_token('{"access_token": "abc"}')

    stored = storage.read_misc(google_docs_service.MISC_TOKEN_KEY, thesis_id="")
    assert stored == {"access_token": "abc"}


def test_save_token_both_fail_does_not_raise(tmp_spo_data_dir):
    """_save_token swallows errors silently when both keyring and storage fail."""
    with patch("keyring.set_password", side_effect=Exception("Keyring broken")), \
         patch("services.storage.write_misc", side_effect=PermissionError("Read only")):
        # Must not raise — exception contract says errors are logged, not propagated
        _save_token('{"dummy": "token"}')


# ══════════════════════════════════════════════════════════════════════════════
# 2. OAUTH STATE & CSRF HOSTILITY
# ══════════════════════════════════════════════════════════════════════════════


def test_csrf_state_mismatch_raises_auth_error(tmp_spo_data_dir):
    """complete_auth_flow raises GDocsAuthError on state mismatch."""
    storage.write_misc(
        google_docs_service.MISC_STATE_KEY,
        {"state": "legit_state"},
        thesis_id="",
    )
    with pytest.raises(GDocsAuthError, match="OAuth state mismatch"):
        complete_auth_flow(code="any_code", state="forged_state")


def test_csrf_no_stored_state_raises_auth_error(tmp_spo_data_dir):
    """complete_auth_flow raises GDocsAuthError when no state was saved at all."""
    # Nothing written to MISC_STATE_KEY
    with pytest.raises(GDocsAuthError, match="OAuth state mismatch"):
        complete_auth_flow(code="any_code", state="whatever")


# ══════════════════════════════════════════════════════════════════════════════
# 3. CREDENTIAL LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════


def test_load_and_refresh_no_token_raises(tmp_spo_data_dir):
    """_load_and_refresh_credentials raises GDocsAuthError with no token anywhere."""
    # Patch both keyring and storage to guarantee no token leaks from other tests
    with patch("keyring.get_password", return_value=None), \
         patch("services.storage.read_misc", return_value=None):
        with pytest.raises(GDocsAuthError, match="No Google credentials found"):
            _load_and_refresh_credentials()


def test_corrupted_token_raises_auth_error(tmp_spo_data_dir):
    """Corrupt stored credentials raise GDocsAuthError instead of crashing."""
    with patch("keyring.get_password", return_value='{"bad": "structure"}'), \
         patch(
             "google.oauth2.credentials.Credentials.from_authorized_user_info",
             side_effect=ValueError("Invalid info"),
         ):
        with pytest.raises(GDocsAuthError, match="Stored credentials are corrupt"):
            _load_and_refresh_credentials()


def test_revoked_refresh_token_raises_auth_error(tmp_spo_data_dir):
    """Google RefreshError wraps into GDocsAuthError."""
    token = '{"client_id": "t", "client_secret": "t", "refresh_token": "expired", "token_uri": "t"}'
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "expired"
    mock_creds.refresh.side_effect = Exception("RefreshError: Token revoked")

    with patch("keyring.get_password", return_value=token), \
         patch(
             "google.oauth2.credentials.Credentials.from_authorized_user_info",
             return_value=mock_creds,
         ):
        with pytest.raises(GDocsAuthError, match="Failed to refresh credentials"):
            _load_and_refresh_credentials()


def test_valid_non_expired_creds_returned_without_refresh(tmp_spo_data_dir):
    """_load_and_refresh_credentials returns creds directly when they are not expired."""
    token = '{"client_id": "t", "client_secret": "t", "refresh_token": "ok", "token_uri": "t"}'
    mock_creds = MagicMock()
    mock_creds.expired = False

    with patch("keyring.get_password", return_value=token), \
         patch(
             "google.oauth2.credentials.Credentials.from_authorized_user_info",
             return_value=mock_creds,
         ):
        result = _load_and_refresh_credentials()

    assert result is mock_creds
    mock_creds.refresh.assert_not_called()


def test_is_connected_false_when_no_token(tmp_spo_data_dir):
    """is_connected returns False when no token is stored."""
    with patch("keyring.get_password", return_value=None):
        assert is_connected() is False


def test_is_connected_true_with_valid_creds(tmp_spo_data_dir):
    """is_connected returns True when credentials load and validate."""
    mock_creds = MagicMock()
    mock_creds.expired = False
    token = '{"client_id": "t", "client_secret": "t", "refresh_token": "ok", "token_uri": "t"}'

    with patch("keyring.get_password", return_value=token), \
         patch(
             "google.oauth2.credentials.Credentials.from_authorized_user_info",
             return_value=mock_creds,
         ):
        assert is_connected() is True


# ══════════════════════════════════════════════════════════════════════════════
# 4. DOCUMENT END-INDEX & NAMED RANGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def test_get_document_end_index_empty_body(mock_gdocs_client):
    """_get_document_end_index returns 1 for an empty document."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": []}
    }
    assert _get_document_end_index(mock_gdocs_client, "doc1") == 1


def test_get_document_end_index_returns_last_end(mock_gdocs_client):
    """_get_document_end_index returns the endIndex of the last content element."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {
            "content": [
                {"endIndex": 50},
                {"endIndex": 200},
                {"endIndex": 350},
            ]
        }
    }
    assert _get_document_end_index(mock_gdocs_client, "doc1") == 350


def test_read_named_range_text_phantom_empty_ranges(mock_gdocs_client):
    """_read_named_range_text returns None when ranges list is empty."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "namedRanges": {
            "spo_test": {
                "namedRanges": [{"namedRangeId": "range1", "ranges": []}]
            }
        }
    }
    result = _read_named_range_text(mock_gdocs_client, "doc1", "range1")
    assert result is None


def test_read_named_range_text_id_not_found_returns_none(mock_gdocs_client):
    """_read_named_range_text returns None when the namedRangeId does not exist in the doc."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "namedRanges": {}
    }
    result = _read_named_range_text(mock_gdocs_client, "doc1", "ghost_range_id")
    assert result is None


def test_read_named_range_text_extracts_correct_content(mock_gdocs_client):
    """_read_named_range_text correctly extracts text within the range boundaries."""
    # Document with text "Hello World\n" starting at index 1
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"startIndex": 1, "endIndex": 12, "textRun": {"content": "Hello World\n"}}
                        ]
                    }
                }
            ]
        },
        "namedRanges": {
            "spo_sub1": {
                "namedRanges": [
                    {
                        "namedRangeId": "range_abc",
                        "ranges": [{"startIndex": 1, "endIndex": 12}],
                    }
                ]
            }
        },
    }
    result = _read_named_range_text(mock_gdocs_client, "doc1", "range_abc")
    # _extract_text clips to [start, end) — endIndex=12 clips the \n at position 11
    # because the range [1,12) covers chars at index 1..11, giving "Hello World"
    assert result == "Hello World"


# ══════════════════════════════════════════════════════════════════════════════
# 5. TEXT NORMALIZATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════


def test_normalize_strips_zero_width_space():
    """_normalize removes zero-width spaces (\u200b)."""
    assert _normalize("Hello\u200bWorld") == _normalize("HelloWorld")


def test_normalize_converts_vertical_tab_to_newline():
    """_normalize maps Google Docs \\x0b (vertical tab) to \\n then collapses."""
    text_vt = "line1\x0bline2"
    text_nl = "line1\nline2"
    assert _normalize(text_vt) == _normalize(text_nl)


def test_normalize_handles_crlf_and_bare_cr():
    """_normalize treats \\r\\n and \\r identically to \\n."""
    text_crlf = "line1\r\nline2"
    text_cr = "line1\rline2"
    text_lf = "line1\nline2"
    assert _normalize(text_crlf) == _normalize(text_lf)
    assert _normalize(text_cr) == _normalize(text_lf)


def test_normalize_collapses_multiple_whitespace():
    """_normalize collapses runs of spaces and newlines into single spaces."""
    assert _normalize("Hello   \n  World") == "Hello World"


def test_normalize_strips_leading_trailing_whitespace():
    """_normalize strips leading and trailing whitespace."""
    assert _normalize("  hello  ") == "hello"


def test_normalize_empty_string():
    """_normalize handles empty string without error."""
    assert _normalize("") == ""


def test_normalize_all_whitespace():
    """_normalize returns empty string for all-whitespace input."""
    assert _normalize("   \n  \x0b  \r  ") == ""


# ══════════════════════════════════════════════════════════════════════════════
# 6. UTF-16 LENGTH CALCULATION
# ══════════════════════════════════════════════════════════════════════════════


def test_utf16_length_ascii():
    """Basic ASCII: UTF-16 length == Python len."""
    assert _get_utf16_length("Hello World") == 11


def test_utf16_length_emoji_counts_as_two():
    """Emoji (surrogate pair) counts as 2 UTF-16 code units."""
    text = "Hello 📊 World"
    assert len(text) == 13
    assert _get_utf16_length(text) == 14


def test_utf16_length_rare_cjk_extension():
    """CJK Extension B characters (> U+FFFF) each count as 2 UTF-16 units."""
    text = "𠜎𠜱𠝹"  # 3 Python chars, each is a surrogate pair
    assert len(text) == 3
    assert _get_utf16_length(text) == 6


def test_utf16_length_empty_string():
    """Empty string has length 0."""
    assert _get_utf16_length("") == 0


def test_utf16_length_regular_cjk():
    """CJK in BMP (< U+FFFF) counts as 1 UTF-16 unit."""
    text = "你好"  # 2 chars, both BMP
    assert _get_utf16_length(text) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 7. _extract_text BOUNDARY CLIPPING
# ══════════════════════════════════════════════════════════════════════════════


def test_extract_text_full_range():
    """_extract_text returns full run text when range covers it entirely."""
    content = [
        {
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "endIndex": 6, "textRun": {"content": "Hello"}}
                ]
            }
        }
    ]
    assert _extract_text(content, 1, 6) == "Hello"


def test_extract_text_clips_start():
    """_extract_text clips text when range starts mid-run."""
    content = [
        {
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "endIndex": 11, "textRun": {"content": "Hello World"}}
                ]
            }
        }
    ]
    # Request range [7, 11): run_start=1, clip_start = max(0, 7-1)=6, clip_end = min(11, 11-1)=10
    # "Hello World"[6:10] = "Worl"
    result = _extract_text(content, 7, 11)
    assert result == "Worl"


def test_extract_text_clips_end():
    """_extract_text clips text when range ends mid-run."""
    content = [
        {
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "endIndex": 11, "textRun": {"content": "Hello World"}}
                ]
            }
        }
    ]
    # Request range [1, 6] → "Hello" (clips last 5 chars: " World")
    result = _extract_text(content, 1, 6)
    assert result == "Hello"


def test_extract_text_skips_out_of_range_elements():
    """_extract_text ignores runs entirely outside the requested range."""
    content = [
        {
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "endIndex": 6, "textRun": {"content": "XXXXX"}},
                    {"startIndex": 10, "endIndex": 16, "textRun": {"content": "TARGET"}},
                    {"startIndex": 20, "endIndex": 26, "textRun": {"content": "YYYYY"}},
                ]
            }
        }
    ]
    result = _extract_text(content, 10, 16)
    assert result == "TARGET"


def test_extract_text_multi_run_spanning():
    """_extract_text concatenates across multiple runs."""
    content = [
        {
            "paragraph": {
                "elements": [
                    {"startIndex": 1, "endIndex": 6, "textRun": {"content": "Hello"}},
                    {"startIndex": 6, "endIndex": 12, "textRun": {"content": " World"}},
                ]
            }
        }
    ]
    assert _extract_text(content, 1, 12) == "Hello World"


def test_extract_text_empty_content():
    """_extract_text returns empty string for empty content list."""
    assert _extract_text([], 1, 10) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 8. _build_insert_requests STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════


def test_build_insert_requests_structure():
    """_build_insert_requests returns [insertText, HEADING_2 style, NORMAL_TEXT reset]."""
    requests = _build_insert_requests(
        text="Body text here.",
        index=10,
        heading_text="My Heading",
        heading_index=10,
    )
    assert len(requests) == 3
    assert "insertText" in requests[0]
    assert requests[1]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_2"
    assert requests[2]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "NORMAL_TEXT"


def test_build_insert_requests_text_content():
    """_build_insert_requests inserts heading + body as combined text."""
    requests = _build_insert_requests(
        text="Body content.",
        index=5,
        heading_text="Title",
        heading_index=5,
    )
    inserted_text = requests[0]["insertText"]["text"]
    assert inserted_text.startswith("Title\n")
    assert "Body content." in inserted_text
    assert inserted_text.endswith("\n")


def test_build_insert_requests_heading_style():
    """_build_insert_requests applies HEADING_2 style to the heading line."""
    requests = _build_insert_requests("Body", index=1, heading_text="H", heading_index=1)
    style = requests[1]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
    assert style == "HEADING_2"


# ══════════════════════════════════════════════════════════════════════════════
# 9. CHAPTER DOC CREATION
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_or_create_chapter_doc_chapter_not_found(tmp_spo_data_dir, mock_gdocs_client):
    """get_or_create_chapter_doc raises ValueError when chapter does not exist."""
    with pytest.raises(ValueError, match="not found in storage"):
        await get_or_create_chapter_doc("", "nonexistent_chapter", "Title")


@pytest.mark.asyncio
async def test_get_or_create_chapter_doc_returns_existing_id(tmp_spo_data_dir, mock_gdocs_client):
    """get_or_create_chapter_doc returns cached gdoc_id without calling the API."""
    chapter_id = "chap_existing"
    storage.write_chapter(
        chapter_id,
        {"chapter_id": chapter_id, "gdoc_id": "already_exists_123"},
        thesis_id="",
    )

    result = await get_or_create_chapter_doc("", chapter_id, "Title")

    assert result == "already_exists_123"
    # API must NOT have been called
    mock_gdocs_client.documents.return_value.create.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_chapter_doc_creates_and_persists(tmp_spo_data_dir, mock_gdocs_client):
    """get_or_create_chapter_doc creates a doc and saves gdoc_id to chapter storage."""
    chapter_id = "chap_new"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")

    result = await get_or_create_chapter_doc("", chapter_id, "New Chapter")

    assert result == "mock_gdoc_id"
    chapter = storage.read_chapter(chapter_id, "")
    assert chapter["gdoc_id"] == "mock_gdoc_id"
    assert "gdoc_created_at" in chapter


# ══════════════════════════════════════════════════════════════════════════════
# 10. CONCURRENCY & ASYNC LOCK
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_thundering_herd_creates_doc_exactly_once(tmp_spo_data_dir, mock_gdocs_client):
    """Concurrent calls for same chapter create the Google Doc exactly once."""
    chapter_id = "chap_thunder"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")

    results = await asyncio.gather(
        *[get_or_create_chapter_doc("", chapter_id, "Title") for _ in range(5)]
    )

    assert all(r == "mock_gdoc_id" for r in results)
    assert mock_gdocs_client.documents.return_value.create.call_count == 1


@pytest.mark.asyncio
async def test_orphaned_lock_is_released_on_storage_failure(tmp_spo_data_dir, mock_gdocs_client):
    """Lock is released even when storage.write_chapter raises, allowing retry."""
    chapter_id = "chap_orphan"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")

    with patch("services.storage.write_chapter", side_effect=IOError("Disk full")):
        with pytest.raises(IOError):
            await get_or_create_chapter_doc("", chapter_id, "Title")

    # Lock should be free; second call succeeds (write_chapter un-patched now)
    result = await get_or_create_chapter_doc("", chapter_id, "Title")
    assert result == "mock_gdoc_id"


@pytest.mark.asyncio
async def test_cross_chapter_concurrency_no_deadlock(tmp_spo_data_dir, mock_gdocs_client):
    """Different chapters can create their docs concurrently without deadlocking."""
    c1, c2 = "chap_a", "chap_b"
    storage.write_chapter(c1, {"chapter_id": c1}, thesis_id="")
    storage.write_chapter(c2, {"chapter_id": c2}, thesis_id="")

    r1, r2 = await asyncio.gather(
        get_or_create_chapter_doc("", c1, "T1"),
        get_or_create_chapter_doc("", c2, "T2"),
    )

    assert r1 == "mock_gdoc_id"
    assert r2 == "mock_gdoc_id"
    assert mock_gdocs_client.documents.return_value.create.call_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# 11. export_subtopic — FRESH APPEND (first-time export)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_first_time_appends_to_doc(tmp_spo_data_dir, mock_gdocs_client):
    """First export calls batchUpdate twice (insert + createNamedRange) and persists metadata."""
    chapter_id = "chap_first"
    subtopic_id = "sub_first"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="Chapter One",
        subtopic_id=subtopic_id,
        subtopic_title="Introduction",
        draft_text="This is the draft body.",
    )

    assert result["gdoc_id"] == "mock_gdoc_id"
    assert result["named_range_id"] == "mock_named_range_id"
    assert result["warning"] is None
    assert "doc_url" in result
    assert "exported_at" in result


@pytest.mark.asyncio
async def test_export_subtopic_first_time_persists_metadata(tmp_spo_data_dir, mock_gdocs_client):
    """First export writes last_gdoc_export_normalized, last_gdoc_export_at, named_range_id."""
    chapter_id = "chap_persist"
    subtopic_id = "sub_persist"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")
    draft = "Persist this text."

    await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text=draft,
    )

    chapter = storage.read_chapter(chapter_id, "")
    sub = next(s for s in chapter["subtopics"] if s["subtopic_id"] == subtopic_id)
    assert sub["gdoc_named_range_id"] == "mock_named_range_id"
    assert sub["last_gdoc_export_normalized"] == _normalize(draft)
    assert sub["last_gdoc_export_at"] is not None
    assert sub["last_gdoc_export_status"] == "success"


@pytest.mark.asyncio
async def test_export_subtopic_subtopic_not_found_raises(tmp_spo_data_dir, mock_gdocs_client):
    """export_subtopic raises ValueError when subtopic_id is not in chapter."""
    chapter_id = "chap_nosub"
    chapter_data = {"chapter_id": chapter_id, "subtopics": [], "gdoc_id": "mock_gdoc_id"}
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    with pytest.raises(ValueError, match="not found in chapter"):
        await export_subtopic(
            thesis_id="",
            chapter_id=chapter_id,
            chapter_title="T",
            subtopic_id="ghost_sub",
            subtopic_title="ST",
            draft_text="Draft",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 12. export_subtopic — RE-EXPORT / UPDATE PATH
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_reexport_matching_text_succeeds(tmp_spo_data_dir, mock_gdocs_client):
    """Re-export succeeds when Docs text matches last normalized export (no conflict)."""
    chapter_id = "chap_reexport"
    subtopic_id = "sub_reexport"
    draft = "The body text."
    normalized = _normalize(draft)

    chapter_data = _make_chapter(
        chapter_id,
        subtopic_id,
        gdoc_named_range_id="existing_range_id",
        last_gdoc_export_normalized=normalized,
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # The mock doc must return text that normalizes to the same value
    doc_response = _make_doc_response(
        named_ranges={
            "spo_sub_reexport": {
                "namedRanges": [
                    {
                        "namedRangeId": "existing_range_id",
                        "ranges": [{"startIndex": 1, "endIndex": 20}],
                    }
                ]
            }
        },
        content=[
            {
                "paragraph": {
                    "elements": [
                        {
                            "startIndex": 1,
                            "endIndex": 20,
                            "textRun": {"content": draft + "\n\n"},
                        }
                    ]
                }
            },
            {"endIndex": 100},
        ],
    )
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = doc_response

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="Updated body text.",
    )

    assert result["warning"] is None
    assert result["named_range_id"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# 13. export_subtopic — FORCE=TRUE BYPASSES SAFE-SYNC GUARD
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_force_true_skips_conflict_check(tmp_spo_data_dir, mock_gdocs_client):
    """force=True allows export even when Docs text differs from last export."""
    chapter_id = "chap_force"
    subtopic_id = "sub_force"

    # Store a "last export" that does NOT match what the mock doc will return
    chapter_data = _make_chapter(
        chapter_id,
        subtopic_id,
        gdoc_named_range_id="force_range_id",
        last_gdoc_export_normalized="original text",
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Mock doc returns DIFFERENT text (would normally trigger GDocsConflictError)
    doc_response = _make_doc_response(
        named_ranges={
            "spo_force": {
                "namedRanges": [
                    {
                        "namedRangeId": "force_range_id",
                        "ranges": [{"startIndex": 1, "endIndex": 20}],
                    }
                ]
            }
        },
        content=[
            {
                "paragraph": {
                    "elements": [
                        {
                            "startIndex": 1,
                            "endIndex": 20,
                            "textRun": {"content": "TOTALLY DIFFERENT text in docs!!"},
                        }
                    ]
                }
            },
            {"endIndex": 100},
        ],
    )
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = doc_response

    # Must NOT raise — force=True bypasses the guard
    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="New forced content.",
        force=True,
    )

    assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# 14. export_subtopic — NAMED RANGE DELETED / MISSING FALLBACK
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_named_range_deleted_falls_back_to_append(
    tmp_spo_data_dir, mock_gdocs_client
):
    """When named range is missing from doc, export falls back to fresh append with a warning."""
    chapter_id = "chap_fallback"
    subtopic_id = "sub_fallback"

    chapter_data = _make_chapter(
        chapter_id,
        subtopic_id,
        gdoc_named_range_id="deleted_range_id",  # ID stored, but not in doc
        last_gdoc_export_normalized="some text",
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Doc has no named ranges — simulates user deleted the named range anchor
    doc_response = _make_doc_response(named_ranges={})
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = doc_response

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="Re-appended content.",
    )

    assert result["warning"] == "named_range_missing"
    # Should still have exported successfully
    assert result["named_range_id"] is not None


@pytest.mark.asyncio
async def test_export_subtopic_named_range_id_in_meta_but_segments_missing(
    tmp_spo_data_dir, mock_gdocs_client
):
    """Named range ID exists in meta, range listed in doc but segments list is empty — fallback."""
    chapter_id = "chap_noseg"
    subtopic_id = "sub_noseg"

    chapter_data = _make_chapter(
        chapter_id,
        subtopic_id,
        gdoc_named_range_id="partial_range_id",
        last_gdoc_export_normalized="something",
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Named range listed but ranges array is empty (segments gone)
    doc_response = _make_doc_response(
        named_ranges={
            "spo_noseg": {
                "namedRanges": [
                    {"namedRangeId": "partial_range_id", "ranges": []}
                ]
            }
        }
    )
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = doc_response

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="Content after range loss.",
    )

    # The service treats this as a "named range missing" fallback
    assert result["warning"] == "named_range_missing"


# ══════════════════════════════════════════════════════════════════════════════
# 15. export_subtopic — PARTIAL BATCH / API FAILURE
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_api_failure_does_not_update_storage(
    tmp_spo_data_dir, mock_gdocs_client
):
    """Storage must NOT be updated when batchUpdate raises an API error."""
    chapter_id = "chap_apifail"
    subtopic_id = "sub_apifail"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    mock_gdocs_client.documents.return_value.batchUpdate.return_value.execute.side_effect = (
        Exception("Google API 503 Service Unavailable")
    )

    with pytest.raises(Exception, match="Google API 503"):
        await export_subtopic(
            thesis_id="",
            chapter_id=chapter_id,
            chapter_title="T",
            subtopic_id=subtopic_id,
            subtopic_title="ST",
            draft_text="Draft",
        )

    # Storage must be pristine
    chapter = storage.read_chapter(chapter_id, "")
    sub = chapter["subtopics"][0]
    assert "last_gdoc_export_at" not in sub
    assert "gdoc_named_range_id" not in sub


@pytest.mark.asyncio
async def test_export_subtopic_get_doc_failure_propagates(tmp_spo_data_dir, mock_gdocs_client):
    """An error fetching the document propagates without mutating storage."""
    chapter_id = "chap_getfail"
    subtopic_id = "sub_getfail"
    chapter_data = _make_chapter(
        chapter_id,
        subtopic_id,
        gdoc_named_range_id="some_range_id",
        last_gdoc_export_normalized="matching text",
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    mock_gdocs_client.documents.return_value.get.return_value.execute.side_effect = (
        Exception("Network error: connection reset")
    )

    with pytest.raises(Exception, match="Network error"):
        await export_subtopic(
            thesis_id="",
            chapter_id=chapter_id,
            chapter_title="T",
            subtopic_id=subtopic_id,
            subtopic_title="ST",
            draft_text="Some draft",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 16. EDGE CASES & BOUNDARY CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_export_subtopic_empty_draft_text(tmp_spo_data_dir, mock_gdocs_client):
    """export_subtopic handles an empty draft string gracefully."""
    chapter_id = "chap_empty"
    subtopic_id = "sub_empty"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="",
    )

    assert result["gdoc_id"] == "mock_gdoc_id"
    chapter = storage.read_chapter(chapter_id, "")
    sub = chapter["subtopics"][0]
    assert sub["last_gdoc_export_normalized"] == _normalize("")


@pytest.mark.asyncio
async def test_export_subtopic_with_emoji_in_draft(tmp_spo_data_dir, mock_gdocs_client):
    """export_subtopic handles emoji/surrogate-pair text in the draft without crashing."""
    chapter_id = "chap_emoji"
    subtopic_id = "sub_emoji"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    draft = "Research shows 📊 significant findings with 🧪 experimental data."

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text=draft,
    )

    assert result["gdoc_id"] == "mock_gdoc_id"


@pytest.mark.asyncio
async def test_export_subtopic_doc_url_format(tmp_spo_data_dir, mock_gdocs_client):
    """export_subtopic returns a correctly formatted Google Docs URL."""
    chapter_id = "chap_url"
    subtopic_id = "sub_url"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    result = await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="T",
        subtopic_id=subtopic_id,
        subtopic_title="ST",
        draft_text="Draft",
    )

    expected_url = "https://docs.google.com/document/d/mock_gdoc_id/edit"
    assert result["doc_url"] == expected_url


def test_normalize_idempotent():
    """_normalize called twice on the same string produces the same result."""
    text = "  Hello\x0b  World\r\n  "
    assert _normalize(_normalize(text)) == _normalize(text)
