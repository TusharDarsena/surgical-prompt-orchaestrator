import pytest
import asyncio
import httpx
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from services.notebooklm_service import (
    _ask_with_retry,
    _run_sequence,
    _run_batch_sequence,
    _run_locks,
    BatchAuthExpiredError
)
from services.notebooklm_service import NLMAuthError
from services import storage

# Helper to create a dummy state setup for testing
def setup_dummy_state(chapter_id="ch1", subtopic_id="sub1", thesis_id="th1"):
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [
            {"subtopic_id": subtopic_id, "source_ids": [{"source_id": "src1", "source_guidance": "Use this."}]}
        ]
    }, thesis_id=thesis_id)
    storage.write_nlm_state(chapter_id, subtopic_id, {"status": "idle"}, thesis_id=thesis_id)


@pytest.mark.asyncio
async def test_ask_with_retry_success(mock_nlm_client):
    # First attempt raises TimeoutException, second succeeds
    mock_result = MagicMock()
    mock_result.answer = "Success answer"
    mock_nlm_client.chat.ask.side_effect = [
        httpx.TimeoutException("Timeout"),
        mock_result
    ]
    
    # Run helper with short retry delay patched to avoid actually waiting 10s
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        answer = await _ask_with_retry(mock_nlm_client, "nb1", "prompt")
        
    assert answer == "Success answer"
    assert mock_nlm_client.chat.ask.call_count == 2
    mock_sleep.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_ask_with_retry_exhaustion(mock_nlm_client):
    # All attempts raise NetworkError
    mock_nlm_client.chat.ask.side_effect = httpx.NetworkError("Network issue")
    
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(RuntimeError, match="chat.ask failed after"):
            await _ask_with_retry(mock_nlm_client, "nb1", "prompt", retries=2)
            
    assert mock_nlm_client.chat.ask.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_run_sequence_stage2_timeout(tmp_spo_data_dir, mock_nlm_client):
    setup_dummy_state()
    
    # Mock Stage 1 success, but Stage 2 add_text times out (we simulate wait_for raising TimeoutError)
    mock_nlm_client.sources.add_text.side_effect = asyncio.TimeoutError("Timeout in add_text")
    
    await _run_sequence(
        chapter_id="ch1", subtopic_id="sub1", 
        chapter={"subtopics": [{"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]}]},
        subtopic={"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]},
        notebook_title="nb", word_count=500, academic_style_notes="", 
        resolved_paths=[{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}], thesis_id="th1"
    )
    
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["status"] == "stage2_error"
    assert "Timeout" in state["error"]
    assert state.get("draft_source_id") is None  # Should not be set if add_text failed
    
    # Verify Draft 1 was actually written to the draft file
    draft = storage.read_section_draft("ch1", "sub1", thesis_id="th1")
    assert draft is not None
    assert draft["text"] == "Mocked LLM answer text"


@pytest.mark.asyncio
async def test_run_sequence_stage2_chat_error(tmp_spo_data_dir, mock_nlm_client):
    setup_dummy_state()
    
    # Mock Stage 1 ask succeeds, add_text succeeds, Stage 2 ask fails entirely
    mock_result_1 = MagicMock()
    mock_result_1.answer = "Draft 1 Content"
    mock_nlm_client.chat.ask.side_effect = [
        mock_result_1, 
        httpx.NetworkError("Network issue"),
        httpx.NetworkError("Network issue"),
        httpx.NetworkError("Network issue") # 3 total attempts for Stage 2
    ]
    
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await _run_sequence(
            chapter_id="ch1", subtopic_id="sub1", 
            chapter={"subtopics": [{"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]}]},
            subtopic={"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]},
            notebook_title="nb", word_count=500, academic_style_notes="", 
            resolved_paths=[{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}], thesis_id="th1"
        )
        
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["status"] == "stage2_error"
    assert "chat.ask failed" in state["error"]
    
    # Crucially, ensure delete was still called on the source ID despite the error
    mock_nlm_client.sources.delete.assert_called_once_with("mock_notebook_id", "mock_source_id")
    

@pytest.mark.asyncio
async def test_run_sequence_add_text_fails(tmp_spo_data_dir, mock_nlm_client):
    setup_dummy_state()
    
    # Mock add_text throwing a direct generic Exception (not a timeout)
    mock_nlm_client.sources.add_text.side_effect = Exception("API broken")
    
    await _run_sequence(
        chapter_id="ch1", subtopic_id="sub1", 
        chapter={"subtopics": [{"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]}]},
        subtopic={"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]},
        notebook_title="nb", word_count=500, academic_style_notes="", 
        resolved_paths=[{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}], thesis_id="th1"
    )
    
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["status"] == "stage2_error"
    assert "API broken" in state["error"]
    assert mock_nlm_client.sources.delete.call_count == 0


@pytest.mark.asyncio
async def test_run_sequence_is_locked(tmp_spo_data_dir, mock_nlm_client):
    setup_dummy_state()
    
    # We want to simulate a long-running _run_sequence so we can fire another one
    # and verify it gets blocked or respects the lock.
    # The lock is per (chapter_id, subtopic_id)
    
    async def slow_ask(*args, **kwargs):
        await asyncio.sleep(0.5)
        mock = MagicMock()
        mock.answer = "Slow answer"
        return mock
        
    mock_nlm_client.chat.ask.side_effect = slow_ask
    
    # Clear lock registry just in case
    _run_locks.clear()
    
    task1 = asyncio.create_task(_run_sequence(
        chapter_id="ch1", subtopic_id="sub1", 
        chapter={"subtopics": [{"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]}]},
        subtopic={"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]},
        notebook_title="nb", word_count=500, academic_style_notes="", 
        resolved_paths=[{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}], thesis_id="th1"
    ))
    
    # Wait slightly so task1 creates and acquires the lock
    await asyncio.sleep(0.1)
    
    # Start task2 on the same subtopic
    task2 = asyncio.create_task(_run_sequence(
        chapter_id="ch1", subtopic_id="sub1", 
        chapter={"subtopics": [{"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]}]},
        subtopic={"subtopic_id": "sub1", "source_ids": [{"source_id": "src1"}]},
        notebook_title="nb", word_count=500, academic_style_notes="", 
        resolved_paths=[{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}], thesis_id="th1"
    ))
    
    # When task2 tries to acquire the lock, it will wait for task1 to finish.
    # We verify that they complete sequentially and run_count correctly hits 2
    # if it runs fully. (Wait, the way the lock works, task2 WILL eventually run
    # once task1 releases it, causing two runs in series. We just verify the lock
    # serializes them).
    
    await asyncio.gather(task1, task2)
    
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["run_count"] == 2
    assert ("ch1", "sub1") not in _run_locks


@pytest.mark.asyncio
async def test_batch_sequence_success(tmp_spo_data_dir, mock_nlm_client):
    for i in range(4):
        setup_dummy_state(subtopic_id=f"sub{i}")
        
    # Run batch
    subtopics_map = {f"sub{i}": {"subtopic_id": f"sub{i}", "source_ids": [{"source_id": "src1"}]} for i in range(4)}
    resolved_paths_map = {f"sub{i}": [{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}] for i in range(4)}
    
    await _run_batch_sequence(
        batch_id="batch1",
        chapter_id="ch1",
        subtopics_map=subtopics_map,
        subtopic_ids=["sub0", "sub1", "sub2", "sub3"],
        word_count=500,
        academic_style_notes="",
        notebook_title_prefix="nb",
        resolved_paths_map=resolved_paths_map,
        thesis_id="th1"
    )
    
    # Check all subtopics finished
    for i in range(4):
        state = storage.read_nlm_state("ch1", f"sub{i}", thesis_id="th1")
        assert state["status"] == "done"
        
    # Check batch state
    batch_state = storage.read_batch_state("batch1", thesis_id="th1")
    assert batch_state["status"] == "done"


@pytest.mark.asyncio
async def test_batch_auth_expiry_aborts_cleanly(tmp_spo_data_dir, mock_nlm_client):
    for i in range(4):
        setup_dummy_state(subtopic_id=f"sub{i}")
        
    # We need to mock _run_sequence directly to raise NLMAuthError for the second subtopic
    # to bypass the concurrency loop complexity and just test the batch orchestrator error handling.
    original_run_sequence = _run_sequence
    
    async def mock_run_seq(chapter_id, subtopic_id, *args, **kwargs):
        if subtopic_id == "sub1":
            raise NLMAuthError("Auth Expired")
        # For others, act normally
        state = storage.read_nlm_state(chapter_id, subtopic_id, thesis_id="th1") or {}
        state["status"] = "done"
        storage.write_nlm_state(chapter_id, subtopic_id, state, thesis_id="th1")
        
    subtopics_map = {f"sub{i}": {"subtopic_id": f"sub{i}", "source_ids": ["src1"]} for i in range(4)}
    resolved_paths_map = {f"sub{i}": [{"path": "fake.pdf", "file_name": "fake.pdf", "drive_file_id": "fake_id"}] for i in range(4)}

    with patch("services.notebooklm_service._run_sequence", side_effect=mock_run_seq):
        with pytest.raises(BatchAuthExpiredError):
            await _run_batch_sequence(
                batch_id="batch1",
                chapter_id="ch1",
                subtopics_map=subtopics_map,
                subtopic_ids=["sub0", "sub1", "sub2", "sub3"],
                word_count=500,
                academic_style_notes="",
                notebook_title_prefix="nb",
                resolved_paths_map=resolved_paths_map,
                thesis_id="th1"
            )
            
    # Sub1 should have no "done" state, and the batch state should reflect the error
    batch_state = storage.read_batch_state("batch1", thesis_id="th1")
    assert batch_state["status"] == "error"
    assert "Auth Expired" in batch_state["error"]
