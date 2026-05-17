import pytest
from fastapi.testclient import TestClient
from main import app
from services import storage

client = TestClient(app)

# Helper to setup state in the tmp path
def setup_state_for_unlock(status, draft_source_id=None, draft_source_title=None, thesis_id="th1"):
    state = {
        "status": status,
        "notebook_id": "mock_notebook_id",
        "draft_source_id": draft_source_id,
        "draft_source_title": draft_source_title,
    }
    storage.write_nlm_state("ch1", "sub1", state, thesis_id=thesis_id)


def test_force_unlock_happy_path(tmp_spo_data_dir, mock_nlm_client):
    setup_state_for_unlock("expanding", draft_source_id="mock_source_id")
    
    response = client.post("/notebooklm/force-unlock/ch1/sub1?thesis_id=th1")
    
    assert response.status_code == 200
    assert response.json()["ok"] is True
    
    # Check that client.sources.delete was called
    mock_nlm_client.sources.delete.assert_called_once_with("mock_notebook_id", "mock_source_id")
    
    # Check state was updated
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["status"] == "stage2_error"
    assert "force-unlocked" in state["error"]
    assert state["draft_source_id"] is None
    assert state["draft_source_title"] is None


def test_force_unlock_invalid_state(tmp_spo_data_dir, mock_nlm_client):
    setup_state_for_unlock("running")  # Must be expanding or stage2_error
    
    response = client.post("/notebooklm/force-unlock/ch1/sub1?thesis_id=th1")
    
    assert response.status_code == 400
    assert "Cannot unlock" in response.json()["detail"]


def test_force_unlock_by_title_fallback(tmp_spo_data_dir, mock_nlm_client):
    # Setup without ID but with title
    setup_state_for_unlock("expanding", draft_source_id=None, draft_source_title="Mock Title")
    
    # Configure sources.list to return a mock source with that title
    class MockSource:
        def __init__(self, id, title):
            self.id = id
            self.title = title
            
    mock_nlm_client.sources.list.return_value = [
        MockSource("other_id", "Other Title"),
        MockSource("target_id", "Mock Title")
    ]
    
    response = client.post("/notebooklm/force-unlock/ch1/sub1?thesis_id=th1")
    assert response.status_code == 200
    
    mock_nlm_client.sources.list.assert_called_once_with("mock_notebook_id")
    mock_nlm_client.sources.delete.assert_called_once_with("mock_notebook_id", "target_id")


def test_force_unlock_swallows_errors(tmp_spo_data_dir, mock_nlm_client):
    setup_state_for_unlock("expanding", draft_source_id="mock_source_id")
    
    # Force delete to throw an exception
    mock_nlm_client.sources.delete.side_effect = Exception("404 Not Found")
    
    response = client.post("/notebooklm/force-unlock/ch1/sub1?thesis_id=th1")
    
    # Should STILL return 200 and update state
    assert response.status_code == 200
    
    state = storage.read_nlm_state("ch1", "sub1", thesis_id="th1")
    assert state["status"] == "stage2_error"
    assert state["draft_source_id"] is None
