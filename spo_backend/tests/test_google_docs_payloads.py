import asyncio
import pytest
from unittest.mock import patch, MagicMock

from services import storage
from services.google_docs_service import export_subtopic, get_or_create_chapter_doc, _normalize
import services.google_docs_service as google_docs_service

# ── Helpers ──────────
def _make_chapter(chapter_id: str, subtopic_id: str = None, **subtopic_kwargs) -> dict:
    chapter = {"chapter_id": chapter_id, "subtopics": []}
    if subtopic_id:
        sub = {"subtopic_id": subtopic_id, **subtopic_kwargs}
        chapter["subtopics"].append(sub)
    return chapter

def _make_doc_response(named_ranges: dict = None, content: list = None) -> dict:
    return {
        "body": {"content": content or [{"endIndex": 100}]},
        "namedRanges": named_ranges or {},
    }
# ────────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# 1. PAYLOAD VALIDATION: FRESH APPEND
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_fresh_append_payload_is_mathematically_correct(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: Verifies that the exact indices and text sent to Google Docs
    are mathematically correct based on UTF-16 lengths and document boundaries.
    """
    chapter_id, subtopic_id = "chap_math", "sub_math"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Force the doc end index to be exactly 100.
    # Therefore, insert_at should be 99 (max(1, 100 - 1)).
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": [{"endIndex": 100}]}
    }

    subtopic_title = "My Header"
    draft_text = "This is a test body."
    
    await export_subtopic(
        thesis_id="",
        chapter_id=chapter_id,
        chapter_title="Chapter Title",
        subtopic_id=subtopic_id,
        subtopic_title=subtopic_title,
        draft_text=draft_text,
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    assert mock_batch.call_count == 2  # 1 for text, 1 for named range

    # Inspect the first batchUpdate (The Text Insertion)
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # 1. Verify Insert Text location
    insert_request = requests[0]["insertText"]
    assert insert_request["location"]["index"] == 99
    assert insert_request["text"] == f"{subtopic_title}\n{draft_text}\n"

    # 2. Verify Heading Style boundaries
    style_request = requests[1]["updateParagraphStyle"]
    assert style_request["range"]["startIndex"] == 99
    # Heading length = len("My Header") = 9. End index = 99 + 9 + 1 = 109.
    assert style_request["range"]["endIndex"] == 109
    assert style_request["paragraphStyle"]["namedStyleType"] == "HEADING_2"


# ══════════════════════════════════════════════════════════════════════════════
# 2. PAYLOAD VALIDATION: RE-EXPORT (UPDATE)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_update_payload_maintains_strict_ordering(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: If the ordering of insert -> style -> delete is altered,
    or the index math shifts, Google Docs will corrupt. This tests the exact payload.
    """
    chapter_id, subtopic_id = "chap_update", "sub_update"
    old_draft = "Old text."
    new_draft = "New text injected."
    
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="range_123",
        last_gdoc_export_normalized=_normalize(old_draft)
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Mock the existing range from indices 50 to 80 (length 30)
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_update": {
                "namedRanges": [{"namedRangeId": "range_123", "ranges": [{"startIndex": 50, "endIndex": 80}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 50, "endIndex": 80, "textRun": {"content": old_draft}}]}}]
    )

    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Title",
        subtopic_id=subtopic_id, subtopic_title="Header", draft_text=new_draft,
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # Verify strict 6-step sequence
    assert len(requests) == 6
    assert "deleteNamedRange" in requests[0]
    assert "insertText" in requests[1]
    assert "updateParagraphStyle" in requests[2]  # HEADING_2
    assert "updateParagraphStyle" in requests[3]  # NORMAL_TEXT
    assert "deleteContentRange" in requests[4]
    assert "createNamedRange" in requests[5]

    # Verify Insert
    assert requests[1]["insertText"]["location"]["index"] == 50
    expected_full_text = f"Header\n{new_draft}\n"
    assert requests[1]["insertText"]["text"] == expected_full_text

    # Verify Delete Content Math
    # Old range was [50, 80]. Old length = 30.
    # New text length: "Header\nNew text injected.\n" -> len is 26
    # Delete range should start at 50 + 26 = 76, and end at 76 + 30 = 106.
    delete_range = requests[4]["deleteContentRange"]["range"]
    assert delete_range["startIndex"] == 76
    assert delete_range["endIndex"] == 106


# ══════════════════════════════════════════════════════════════════════════════
# 3. EDGE CASES & NETWORK FAILURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_or_create_doc_handles_empty_string_id(tmp_spo_data_dir, mock_gdocs_client):
    """
    BREAKING SCENARIO: If a bug writes `""` to gdoc_id instead of null/None, 
    the system must still realize the doc doesn't exist and create it.
    """
    chapter_id = "chap_empty_string"
    # Note the explicit empty string, which evaluates to False
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id, "gdoc_id": ""}, thesis_id="")

    mock_gdocs_client.documents.return_value.create.return_value.execute.return_value = {
        "documentId": "freshly_minted_id"
    }

    result = await get_or_create_chapter_doc("", chapter_id, "Title")

    assert result == "freshly_minted_id"
    mock_gdocs_client.documents.return_value.create.assert_called_once()

@pytest.mark.asyncio
async def test_export_subtopic_api_hang_releases_lock(tmp_spo_data_dir, mock_gdocs_client):
    """
    BREAKING SCENARIO: If the Google API times out during doc creation,
    the lock must be released so subsequent retries don't deadlock.
    """
    chapter_id = "chap_timeout"
    storage.write_chapter(chapter_id, {"chapter_id": chapter_id}, thesis_id="")

    # Simulate a Timeout from the Google API
    mock_gdocs_client.documents.return_value.create.side_effect = TimeoutError("Google is down")

    with pytest.raises(TimeoutError):
        await get_or_create_chapter_doc("", chapter_id, "Title")

    # The lock should be free now. We verify by calling it again with a successful mock.
    mock_gdocs_client.documents.return_value.create.side_effect = None
    mock_gdocs_client.documents.return_value.create.return_value.execute.return_value = {
        "documentId": "second_try_id"
    }

    result = await get_or_create_chapter_doc("", chapter_id, "Title")
    assert result == "second_try_id"


# ══════════════════════════════════════════════════════════════════════════════
# 17. ADVANCED EDGE CASES & API MALFORMATIONS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_corrupted_named_range_falls_back_to_append(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: The Google API returns the named range ID, but the actual 
    'ranges' array is missing or null. The code must not crash on IndexError and 
    should seamlessly fall back to a fresh append at the bottom of the document.
    """
    chapter_id, subtopic_id = "chap_corrupt", "sub_corrupt"
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="corrupted_range",
        last_gdoc_export_normalized="old text"
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Mock doc response where ranges is entirely missing from the payload
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": [{"endIndex": 200}]},
        "namedRanges": {
            "spo_corrupt": {
                "namedRanges": [{"namedRangeId": "corrupted_range"}] # NO 'ranges' key!
            }
        }
    }

    result = await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Title",
        subtopic_id=subtopic_id, subtopic_title="Header", draft_text="Draft",
    )

    # Must warn and fallback
    assert result["warning"] == "named_range_missing"
    
    # Verify the fallback triggered a Fresh Append payload (3 steps, not 6)
    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]
    
    assert len(requests) == 3  # insertText + HEADING_2 + NORMAL_TEXT (fresh append)
    assert "insertText" in requests[0]
    # Verify it inserted at the bottom (200 - 1 = 199)
    assert requests[0]["insertText"]["location"]["index"] == 199

@pytest.mark.asyncio
async def test_export_subtopic_empty_document_boundary(tmp_spo_data_dir, mock_gdocs_client):
    """
    BREAKING SCENARIO: A completely empty Google Doc has an endIndex of 1. 
    The math `doc_end - 1` would be 0, but Google Docs throws a 400 error if you 
    insert at index 0. The code must clamp the minimum insert index to 1.
    """
    chapter_id, subtopic_id = "chap_bound", "sub_bound"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Completely empty document payload
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": []}
    }

    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="T",
        subtopic_id=subtopic_id, subtopic_title="H", draft_text="Body",
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    insert_req = kwargs["body"]["requests"][0]["insertText"]
    
    # MUST be 1, not 0
    assert insert_req["location"]["index"] == 1

# ══════════════════════════════════════════════════════════════════════════════
# 18. OAUTH PKCE & STATE VERIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def test_get_auth_url_saves_csrf_and_pkce_state(tmp_spo_data_dir):
    """
    BREAKING SCENARIO: If the Auth URL generation doesn't write state to storage,
    the callback will permanently fail.
    """
    # Mock Flow to return predictable url and state, and attach a PKCE verifier
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("http://auth.url", "secure_state")
    mock_flow.code_verifier = "pkce_secret"

    with patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file", return_value=mock_flow), \
         patch("os.path.exists", return_value=True):
        url = google_docs_service.get_auth_url()

    assert url == "http://auth.url"
    
    # Verify both state and verifier made it to disk
    stored = storage.read_misc(google_docs_service.MISC_STATE_KEY, thesis_id="")
    assert stored["state"] == "secure_state"
    assert stored["code_verifier"] == "pkce_secret"

def test_complete_auth_flow_handles_missing_pkce_gracefully(tmp_spo_data_dir):
    """
    BREAKING SCENARIO: If a user started the flow on an older version of the app 
    that didn't save `code_verifier`, the callback shouldn't crash with a KeyError.
    """
    # Simulate valid state, but no code_verifier saved
    storage.write_misc(
        google_docs_service.MISC_STATE_KEY, 
        {"state": "legit_state"}, # Missing code_verifier
        thesis_id=""
    )

    mock_flow = MagicMock()
    # Mock the flow so we don't actually hit Google
    mock_flow.credentials.to_json.return_value = '{"token": "ok"}'

    with patch("google_auth_oauthlib.flow.Flow.from_client_secrets_file", return_value=mock_flow):
        # Must not raise an exception
        google_docs_service.complete_auth_flow("auth_code", "legit_state")

    # Ensure fetch_token was still called
    mock_flow.fetch_token.assert_called_once_with(code="auth_code")


# ══════════════════════════════════════════════════════════════════════════════
# 19. NON-ATOMIC API FRACTURES & RACE CONDITIONS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_two_step_fracture_leaves_storage_clean(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: In a fresh append, inserting text and creating the named 
    range are two separate API calls. If the second fails, the code must raise 
    an exception so the caller knows the sync is fractured, and storage must 
    NOT be updated with a success state.
    """
    chapter_id, subtopic_id = "chap_fracture", "sub_fracture"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Setup the mock to succeed on the 1st call (Insert Text), but FAIL on the 2nd (Create Range)
    mock_batch = mock_gdocs_client.documents().batchUpdate
    mock_batch.return_value.execute.side_effect = [
        {"replies": []},  # 1st call succeeds
        Exception("Google API 500: Internal Error on Named Range Creation") # 2nd call fails
    ]

    with pytest.raises(Exception, match="Named Range Creation"):
        await export_subtopic(
            thesis_id="", chapter_id=chapter_id, chapter_title="T",
            subtopic_id=subtopic_id, subtopic_title="H", draft_text="Draft",
        )

    # Verify storage remains completely untouched regarding metadata
    chapter = storage.read_chapter(chapter_id, "")
    sub = chapter["subtopics"][0]
    assert "gdoc_named_range_id" not in sub
    assert "last_gdoc_export_at" not in sub

@pytest.mark.asyncio
async def test_export_subtopic_phantom_subtopic_race_condition(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: If the subtopic is deleted from the database WHILE the 
    Google API is processing, the final read-merge-write loop will fail to find 
    the subtopic. It must not crash with a KeyError/IndexError.
    """
    chapter_id, subtopic_id = "chap_race", "sub_race"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # We need to simulate the database changing while the async API call happens.
    # We will hijack the batchUpdate mock to delete the subtopic from storage mid-flight.
    def mock_execute_side_effect(*args, **kwargs):
        mutated_chapter = {"chapter_id": chapter_id, "subtopics": [], "gdoc_id": "mock_gdoc_id"}
        storage.write_chapter(chapter_id, mutated_chapter, thesis_id="")
        return {"replies": [{"createNamedRange": {"namedRangeId": "new_range"}}]}

    mock_gdocs_client.documents().batchUpdate.return_value.execute.side_effect = mock_execute_side_effect

    # This should complete without crashing, even though the subtopic vanished
    result = await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="T",
        subtopic_id=subtopic_id, subtopic_title="H", draft_text="Draft",
    )

    # The function itself succeeds, but if we check storage, no metadata was saved
    # because the loop `for sub in chapter.get("subtopics", [])` found nothing.
    final_chapter = storage.read_chapter(chapter_id, "")
    assert len(final_chapter["subtopics"]) == 0
    assert result["named_range_id"] == "new_range"


# ══════════════════════════════════════════════════════════════════════════════
# 20. TEXT EXTRACTION & FORMATTING ANOMALIES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_empty_title_formatting_boundaries(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: If subtopic_title is an empty string, the style application 
    range must safely format just the newline character without inverting indices.
    """
    chapter_id, subtopic_id = "chap_notitle", "sub_notitle"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": [{"endIndex": 50}]} # Insert at 49
    }

    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="T",
        subtopic_id=subtopic_id, subtopic_title="", draft_text="Body only", # EMPTY TITLE
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # Insert text should just be "\nBody only\n"
    assert requests[0]["insertText"]["text"] == "\nBody only\n"
    
    # Style boundary check: insert_at = 49. length = 0. End index = 49 + 0 + 1 = 50.
    style_req = requests[1]["updateParagraphStyle"]["range"]
    assert style_req["startIndex"] == 49
    assert style_req["endIndex"] == 50

def test_extract_text_silently_ignores_tables():
    """
    BREAKING SCENARIO: Proves that _extract_text ignores complex structural 
    elements like Tables, which could cause a false-positive ConflictError 
    if the user added a table manually inside the named range.
    """
    from services.google_docs_service import _extract_text

    # Document content containing a Paragraph and a Table
    content = [
        {
            "paragraph": {
                "elements": [{"startIndex": 1, "endIndex": 6, "textRun": {"content": "Text\n"}}]
            }
        },
        {
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {"content": [{"paragraph": {"elements": [{"startIndex": 7, "endIndex": 12, "textRun": {"content": "Data"}}]}}]}
                        ]
                    }
                ]
            }
        }
    ]

    # Try to extract the entire range
    result = _extract_text(content, 1, 12)
    
    # It will only return the paragraph text, completely dropping the table "Data"
    # because the loop does not recursively search inside `table` keys.
    assert result == "Text\n"


# ══════════════════════════════════════════════════════════════════════════════
# 21. DATA LOSS PREVENTION: OVERWRITES & LEAKS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_update_prevents_spillover_overwrite(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    DATA LOSS SCENARIO: If the user updates Subtopic A, the delete operation 
    must perfectly stop at the boundary of Subtopic A. If the math overshoots, 
    it will silently delete the beginning of Subtopic B.
    """
    chapter_id, subtopic_id = "chap_spill", "sub_spill"
    
    # Old text length is exactly 20 characters
    old_draft = "01234567890123456789" 
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="range_a",
        last_gdoc_export_normalized=_normalize(old_draft)
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Mock doc where Subtopic A is at [10, 30] and Subtopic B starts right at 30
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_spill": {
                "namedRanges": [{"namedRangeId": "range_a", "ranges": [{"startIndex": 10, "endIndex": 30}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 10, "endIndex": 30, "textRun": {"content": old_draft}}]}}]
    )

    # User writes a slightly longer new draft
    new_draft = "This is the new text" # Length 20
    subtopic_title = "Title" # Length 5
    # Full new text inserted: "Title\nThis is the new text\n" -> Length = 5 + 1 + 20 + 1 = 27
    
    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Chap",
        subtopic_id=subtopic_id, subtopic_title=subtopic_title, draft_text=new_draft,
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # Verify Delete Content Math
    # Insert happens at 10. New text shifts old text forward by 27 indices.
    # Therefore, the old text now lives exactly at [37, 57].
    delete_range = requests[4]["deleteContentRange"]["range"]
    
    # CRITICAL ASSERTION: If endIndex > 57, you just deleted another subtopic's data.
    assert delete_range["startIndex"] == 37
    assert delete_range["endIndex"] == 57


@pytest.mark.asyncio
async def test_export_subtopic_update_shrinking_text_cleans_up_ghosts(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    DATA LOSS SCENARIO: The user had a massive draft (1000 chars) and edited it 
    down to a tiny draft (50 chars). If the delete operation calculates length based 
    on the NEW text instead of the OLD text, 950 characters of "ghost text" will 
    be permanently stranded in the document.
    """
    chapter_id, subtopic_id = "chap_shrink", "sub_shrink"
    
    # Simulate a massive old draft (length 1000)
    old_draft = "X" * 1000
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="range_massive",
        last_gdoc_export_normalized=_normalize(old_draft)
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Old text lives at [100, 1100]
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_shrink": {
                "namedRanges": [{"namedRangeId": "range_massive", "ranges": [{"startIndex": 100, "endIndex": 1100}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 100, "endIndex": 1100, "textRun": {"content": old_draft}}]}}]
    )

    # User shrinks draft to just "Tiny"
    new_draft = "Tiny" 
    subtopic_title = "T"
    # Full new inserted length: "T\nTiny\n" -> length 7
    
    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Chap",
        subtopic_id=subtopic_id, subtopic_title=subtopic_title, draft_text=new_draft,
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    delete_range = requests[4]["deleteContentRange"]["range"]
    
    # CRITICAL ASSERTION:
    # Inserted 7 chars at 100. Old text shifted to 107.
    # Old text length was 1000. 
    # It must delete from 107 to 1107 to clean up the entire massive draft.
    assert delete_range["startIndex"] == 107
    assert delete_range["endIndex"] == 1107


@pytest.mark.asyncio
async def test_export_subtopic_update_expanding_text_does_not_eat_itself(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    DATA LOSS SCENARIO: The user expands a tiny draft into a massive draft. 
    If the index math uses the wrong length variable, the `deleteContentRange` 
    will accidentally delete the brand new text it just inserted.
    """
    chapter_id, subtopic_id = "chap_expand", "sub_expand"
    
    # Simulate a tiny old draft (length 10)
    old_draft = "Old text.." 
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="range_tiny",
        last_gdoc_export_normalized=_normalize(old_draft)
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Old text lives at [50, 60]
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_expand": {
                "namedRanges": [{"namedRangeId": "range_tiny", "ranges": [{"startIndex": 50, "endIndex": 60}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 50, "endIndex": 60, "textRun": {"content": old_draft}}]}}]
    )

    # User expands draft massively
    new_draft = "Y" * 500
    subtopic_title = "Title"
    # Full new inserted length: "Title\n" + 500 chars + "\n" -> length 507
    
    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Chap",
        subtopic_id=subtopic_id, subtopic_title=subtopic_title, draft_text=new_draft,
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    delete_range = requests[4]["deleteContentRange"]["range"]
    
    # CRITICAL ASSERTION:
    # Inserted 507 chars at 50. Old text shifted to 557.
    # It MUST ONLY delete the old 10 characters: from 557 to 567.
    # If it starts deleting at 50 or deletes 507 characters, new data is lost.
    assert delete_range["startIndex"] == 557
    assert delete_range["endIndex"] == 567


def test_extract_text_handles_utf16_surrogate_pairs_correctly():
    """
    BREAKING SCENARIO: Google Docs indices are UTF-16. Python strings are Unicode.
    If draft text contains emojis or complex characters, slicing by Docs indices 
    will slice Python strings incorrectly, corrupting the text read-back.
    """
    from services.google_docs_service import _extract_text

    text_content = "Rocket 🚀! Hello"
    
    # Simulate a Google Docs content payload
    content = [
        {
            "paragraph": {
                "elements": [{"startIndex": 0, "endIndex": 16, "textRun": {"content": text_content}}]
            }
        }
    ]

    # We want to extract UTF-16 indices 1 to 10.
    # UTF-16 indices:
    # 0: R, 1: o, 2: c, 3: k, 4: e, 5: t, 6: space, 7-8: 🚀, 9: !, 10: space, 11: H...
    # Indices 1 to 10 (exclusive of 10) means we want from 'o' to '!'
    # So we should get "ocket 🚀!"
    
    extracted = _extract_text(content, 1, 10)
    
    assert extracted == "ocket 🚀!", f"BUG EXPOSED: Extracted text mangled as '{extracted}'"


@pytest.mark.asyncio
async def test_export_subtopic_idempotent_update_prevents_false_conflict(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    BREAKING SCENARIO: The system saves ONLY `draft_text` to normalization state, 
    but reads back `Title + draft_text` from Docs. This test exposes the false 409.
    """
    chapter_id, subtopic_id = "chap_idem", "sub_idem"
    subtopic_title = "My Academic Header"
    draft_text = "This is the draft text."
    
    # 1. Simulate the exact state saved AFTER a successful first export
    chapter_data = _make_chapter(
        chapter_id, subtopic_id, 
        gdoc_named_range_id="range_123",
        # FIXED: State now contains title + draft_text
        last_gdoc_export_normalized=_normalize(f"{subtopic_title}\n{draft_text}\n") 
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # 2. Simulate what Google Docs actually returns (Title + Draft + Newlines)
    docs_returned_text = f"{subtopic_title}\n{draft_text}\n"
    
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_idem": {
                "namedRanges": [{"namedRangeId": "range_123", "ranges": [{"startIndex": 10, "endIndex": 53}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 10, "endIndex": 53, "textRun": {"content": docs_returned_text}}]}}]
    )

    # 3. Attempt to export the exact same text again. 
    # This SHOULD succeed seamlessly, but will raise a GDocsConflictError on your current codebase.
    try:
        await export_subtopic(
            thesis_id="", chapter_id=chapter_id, chapter_title="Chapter",
            subtopic_id=subtopic_id, subtopic_title=subtopic_title, draft_text=draft_text,
            force=False # Ensure safe sync is ON
        )
    except google_docs_service.GDocsConflictError as e:
        pytest.fail(f"BUG EXPOSED: False 409 Conflict thrown. Expected '{e.spo_excerpt}' to match '{e.gdoc_excerpt}'")
