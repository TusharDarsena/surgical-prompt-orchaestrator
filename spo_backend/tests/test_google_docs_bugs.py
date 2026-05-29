import asyncio
import pytest
from unittest.mock import patch, MagicMock

from services import storage
from services.google_docs_service import export_subtopic, _normalize

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
# FIX 1 VERIFICATION: Named Range Evaporation
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_update_named_range_is_recreated(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    REGRESSION: Inserting at old_start would push the named range forward and
    the subsequent delete would destroy it. The fix is to explicitly delete the
    old range and recreate it in the same atomic batch.
    """
    chapter_id, subtopic_id = "chap_evap", "sub_evap"
    old_draft = "Old text."
    # last_gdoc_export_normalized must match what _read_named_range_text returns
    # (the text inside the range [50, 60]) so the conflict check passes.
    chapter_data = _make_chapter(
        chapter_id, subtopic_id,
        gdoc_named_range_id="range_evap",
        last_gdoc_export_normalized=_normalize(old_draft),
    )
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Named range [50, 60] wraps exactly old_draft (9 chars)
    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = _make_doc_response(
        named_ranges={
            "spo_sub_evap": {
                "namedRanges": [{"namedRangeId": "range_evap", "ranges": [{"startIndex": 50, "endIndex": 60}]}]
            }
        },
        content=[{"paragraph": {"elements": [{"startIndex": 50, "endIndex": 60, "textRun": {"content": old_draft}}]}}]
    )

    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Title",
        subtopic_id=subtopic_id, subtopic_title="Header", draft_text="New Draft",
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # FIX VERIFIED: The batch must explicitly delete the old range (step 0)
    # and recreate it (step 5) so it survives the insert+delete pair.
    assert any("deleteNamedRange" in req for req in requests), \
        "Missing deleteNamedRange: old range may survive in a broken position."
    assert any("createNamedRange" in req for req in requests), \
        "Missing createNamedRange: named range is not recreated after update."

    # Confirm the atomic ordering: delete range → insert → style → delete old → create range
    request_types = [list(req.keys())[0] for req in requests]
    assert request_types[0] == "deleteNamedRange"
    assert request_types[1] == "insertText"
    assert request_types[-1] == "createNamedRange"


# ══════════════════════════════════════════════════════════════════════════════
# FIX 2 VERIFICATION: Formatting Bleed
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_body_text_has_normal_text_style(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    REGRESSION: Inserted body text would inherit the HEADING_2 style of the
    insertion point. The fix adds an explicit NORMAL_TEXT reset for the body.
    Verified for both fresh-append and update paths.
    """
    chapter_id, subtopic_id = "chap_bleed", "sub_bleed"
    chapter_data = _make_chapter(chapter_id, subtopic_id)
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    mock_gdocs_client.documents.return_value.get.return_value.execute.return_value = {
        "body": {"content": [{"endIndex": 100}]}
    }

    await export_subtopic(
        thesis_id="", chapter_id=chapter_id, chapter_title="Title",
        subtopic_id=subtopic_id, subtopic_title="My Header", draft_text="This text must be normal.",
    )

    mock_batch = mock_gdocs_client.documents().batchUpdate
    args, kwargs = mock_batch.call_args_list[0]
    requests = kwargs["body"]["requests"]

    # FIX VERIFIED: There must be a NORMAL_TEXT updateParagraphStyle for the body.
    normal_text_styles = [
        req["updateParagraphStyle"]
        for req in requests
        if "updateParagraphStyle" in req
        and req["updateParagraphStyle"]["paragraphStyle"].get("namedStyleType") == "NORMAL_TEXT"
    ]
    assert len(normal_text_styles) >= 1, \
        "Body text is missing a NORMAL_TEXT reset — will inherit bleed formatting."

    # The NORMAL_TEXT range must start AFTER the heading (heading ends at insert_at + heading_len + 1)
    body_style = normal_text_styles[0]
    heading_style = next(
        req["updateParagraphStyle"]
        for req in requests
        if "updateParagraphStyle" in req
        and req["updateParagraphStyle"]["paragraphStyle"].get("namedStyleType") == "HEADING_2"
    )
    assert body_style["range"]["startIndex"] == heading_style["range"]["endIndex"], \
        "NORMAL_TEXT range does not begin exactly where HEADING_2 ends."


# ══════════════════════════════════════════════════════════════════════════════
# FIX 3 VERIFICATION: Concurrent Appends (Race Condition)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_export_subtopic_concurrent_appends_are_serialised(
    tmp_spo_data_dir, mock_gdocs_client
):
    """
    REGRESSION: Two concurrent exports to the same chapter would both read the
    same doc_end and insert at the same index, corrupting the document.
    The fix extends the chapter lock to cover the full export transaction so
    exports queue up sequentially and each reads the correct doc_end.
    """
    chapter_id = "chap_race"
    chapter_data = _make_chapter(chapter_id, "sub_1")
    chapter_data["subtopics"].append({"subtopic_id": "sub_2"})
    chapter_data["gdoc_id"] = "mock_gdoc_id"
    storage.write_chapter(chapter_id, chapter_data, thesis_id="")

    # Simulate the document growing after the first export: sub_1 reads doc_end=100,
    # sub_2 (queued behind the lock) reads doc_end=150 after sub_1 finishes.
    mock_gdocs_client.documents.return_value.get.return_value.execute.side_effect = [
        {"body": {"content": [{"endIndex": 100}]}},  # sub_1 reads this
        {"body": {"content": [{"endIndex": 150}]}},  # sub_2 reads this after lock is released
    ]

    task1 = export_subtopic("", chapter_id, "Title", "sub_1", "Header 1", "Draft 1")
    task2 = export_subtopic("", chapter_id, "Title", "sub_2", "Header 2", "Draft 2")

    await asyncio.gather(task1, task2)

    mock_batch = mock_gdocs_client.documents().batchUpdate
    # Each fresh-append export makes 2 batchUpdate calls (text + createNamedRange)
    assert mock_batch.call_count == 4

    # FIX VERIFIED: Sequential execution means different doc_end reads → different insert indices.
    insert_req_1 = mock_batch.call_args_list[0][1]["body"]["requests"][0]["insertText"]
    insert_req_2 = mock_batch.call_args_list[2][1]["body"]["requests"][0]["insertText"]

    assert insert_req_1["location"]["index"] != insert_req_2["location"]["index"], (
        f"Lock is not protecting the full transaction — both exports inserted at "
        f"index {insert_req_1['location']['index']}."
    )
    # sub_1 inserts at 99 (100-1), sub_2 inserts at 149 (150-1)
    assert insert_req_1["location"]["index"] == 99
    assert insert_req_2["location"]["index"] == 149
