import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock

from services import storage
from services import google_docs_service
from services.google_docs_service import (
    GDocsAuthError,
    GDocsConflictError,
    _save_token,
    _load_and_refresh_credentials,
    complete_auth_flow,
    get_or_create_chapter_doc,
    export_subtopic,
    _read_named_range_text,
    _get_document_end_index,
    _get_utf16_length,
    _normalize
)

# ── 1. Token Storage & Environment Failures ────────────────────────────────────

def test_schrodingers_keyring(tmp_spo_data_dir):
    """Fallback to storage.read_misc executes smoothly when keyring fails."""
    # Ensure misc storage has a token
    storage.write_misc(google_docs_service.MISC_TOKEN_KEY, {"dummy": "token"}, thesis_id="")
    
    with patch("keyring.get_password", side_effect=Exception("Keyring broken")):
        token_json = google_docs_service._load_token()
        assert json.loads(token_json) == {"dummy": "token"}


def test_read_only_fallback(tmp_spo_data_dir):
    """Write permission error on misc storage shouldn't crash _save_token if keyring fails."""
    with patch("keyring.set_password", side_effect=Exception("Keyring broken")), \
         patch("services.storage.write_misc", side_effect=PermissionError("Read only")):
        # We wrapped it in a try/except, so it shouldn't raise
        _save_token('{"dummy": "token"}')


def test_corrupted_token_state(tmp_spo_data_dir):
    """Corrupt token JSON is caught and translated to GDocsAuthError."""
    # Write invalid json to misc storage
    storage.write_misc(google_docs_service.MISC_TOKEN_KEY, {"bad": "structure"}, thesis_id="")
    
    with patch("keyring.get_password", return_value='{"bad": "structure"}'), \
         patch("google.oauth2.credentials.Credentials.from_authorized_user_info", side_effect=ValueError("Invalid info")):
        with pytest.raises(GDocsAuthError):
            _load_and_refresh_credentials()


# ── 2. OAuth State & CSRF Hostility ────────────────────────────────────────────

def test_csrf_collision(tmp_spo_data_dir):
    """State mismatch correctly raises GDocsAuthError."""
    storage.write_misc(google_docs_service.MISC_STATE_KEY, {"state": "valid_state"}, thesis_id="")
    with pytest.raises(GDocsAuthError, match="OAuth state mismatch"):
        complete_auth_flow(code="some_code", state="invalid_state")


def test_revoked_refresh_token(tmp_spo_data_dir):
    """Google RefreshError wraps into GDocsAuthError."""
    # Setup valid-looking token so it passes parsing but fails refresh
    token = '{"client_id": "test", "client_secret": "test", "refresh_token": "expired", "token_uri": "test"}'
    
    # Needs to be "expired" in memory so refresh is triggered
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "expired"
    mock_creds.refresh.side_effect = Exception("RefreshError: Token revoked")
    
    with patch("keyring.get_password", return_value=token), \
         patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds):
        with pytest.raises(GDocsAuthError, match="Failed to refresh credentials"):
            _load_and_refresh_credentials()


# ── 3. Concurrency & The Async Event Loop ──────────────────────────────────────

@pytest.mark.asyncio
async def test_thundering_herd(tmp_spo_data_dir, mock_gdocs_client):
    """Ensure doc creation lock limits Google API calls to exactly 1 per chapter."""
    chapter_id = "chap_thunder"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")
    
    # Gather 5 simultaneous calls
    coros = [get_or_create_chapter_doc("", chapter_id, "Title") for _ in range(5)]
    results = await asyncio.gather(*coros)
    
    # All should return the same doc ID
    assert all(r == "mock_gdoc_id" for r in results)
    
    # API should have been called exactly once
    doc_methods = mock_gdocs_client.documents.return_value
    assert doc_methods.create.call_count == 1


@pytest.mark.asyncio
async def test_orphaned_lock(tmp_spo_data_dir, mock_gdocs_client):
    """Lock is released even if storage.write_chapter throws an error."""
    chapter_id = "chap_orphan"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")
    
    with patch("services.storage.write_chapter", side_effect=IOError("Disk full")):
        with pytest.raises(IOError):
            await get_or_create_chapter_doc("", chapter_id, "Title")
            
    # Lock should be free, so second call can proceed
    with patch("services.storage.write_chapter"): # remove exception
        await get_or_create_chapter_doc("", chapter_id, "Title")


@pytest.mark.asyncio
async def test_cross_chapter_deadlock(tmp_spo_data_dir, mock_gdocs_client):
    """Multiple chapters can create docs concurrently."""
    c1, c2 = "chap1", "chap2"
    storage.write_chapter(c1, {"chapter_id": c1}, thesis_id="")
    storage.write_chapter(c2, {"chapter_id": c2}, thesis_id="")
    
    # Run two different chapters simultaneously
    res1, res2 = await asyncio.gather(
        get_or_create_chapter_doc("", c1, "T1"),
        get_or_create_chapter_doc("", c2, "T2")
    )
    assert res1 == "mock_gdoc_id"
    assert res2 == "mock_gdoc_id"
    # Should have called create twice (once for each chapter)
    doc_methods = mock_gdocs_client.documents.return_value
    assert doc_methods.create.call_count == 2


# ── 4. Google Docs Document State Corruption ───────────────────────────────────

def test_phantom_named_range(mock_gdocs_client):
    """If ranges array is empty, _read_named_range_text safely returns None."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "namedRanges": {
            "spo_test": {"namedRanges": [{"namedRangeId": "range1", "ranges": []}]}
        }
    }
    result = _read_named_range_text(mock_gdocs_client, "doc1", "range1")
    assert result is None


@pytest.mark.asyncio
async def test_partial_batch_failure(tmp_spo_data_dir, mock_gdocs_client):
    """Storage write does not occur if batchUpdate fails."""
    chapter_id = "chap_batch"
    subtopic_id = "sub_batch"
    
    chapter_data = {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")
    
    doc_methods = mock_gdocs_client.documents.return_value
    doc_methods.batchUpdate.return_value.execute.side_effect = Exception("API Error")
    
    with pytest.raises(Exception, match="API Error"):
        await export_subtopic("", chapter_id, "T", subtopic_id, "ST", "Draft")
        
    # Read state, should not be updated
    chapter = storage.read_chapter(chapter_id, "")
    sub = chapter["subtopics"][0]
    assert "last_gdoc_export_at" not in sub


def test_empty_document_end_index(mock_gdocs_client):
    """_get_document_end_index returns 1 if content is empty."""
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": []}
    }
    assert _get_document_end_index(mock_gdocs_client, "doc1") == 1


# ── 5. Safe Sync & The Text Normalization Engine ───────────────────────────────

def test_utf16_indexing_mismatch():
    """Verify that _get_utf16_length correctly accounts for surrogate pairs."""
    text_normal = "Hello World"
    assert _get_utf16_length(text_normal) == 11
    
    text_emoji = "Hello 📊 World"
    # Python len is 13, but emoji is 2 utf-16 code units, so total is 14
    assert len(text_emoji) == 13
    assert _get_utf16_length(text_emoji) == 14
    
    text_surrogate = "𠜎𠜱𠝹"
    assert len(text_surrogate) == 3
    assert _get_utf16_length(text_surrogate) == 6


def test_invisible_edit_guard():
    """Verify _normalize strips zero-width spaces."""
    text_with_zws = "Hello\u200bWorld"
    text_without_zws = "HelloWorld"
    
    assert _normalize(text_with_zws) == _normalize(text_without_zws)
