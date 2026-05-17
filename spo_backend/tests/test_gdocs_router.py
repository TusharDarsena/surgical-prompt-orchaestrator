import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from routers import gdocs
from services import storage
from services.google_docs_service import (
    GDocsConflictError,
    GDocsNotConfiguredError,
    GDocsAuthError
)

# Mocking the FastAPI app - we can just test the router functions directly, 
# or mount it to a test app.
from fastapi import FastAPI
app = FastAPI()
app.include_router(gdocs.router)

client = TestClient(app)

# ── 6. Router Exception Mapping (The Contract Guard) ───────────────────────────

def test_status_code_trap_conflict(tmp_spo_data_dir):
    """Router catches GDocsConflictError and returns 409."""
    chapter_id = "chap_status"
    subtopic_id = "sub_status"
    
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }, thesis_id="")
    storage.write_section_draft(chapter_id, subtopic_id, {"text": "Draft content"}, thesis_id="")
    
    with patch("routers.gdocs.export_subtopic", side_effect=GDocsConflictError("gdoc", "spo", "2026")):
        resp = client.post("/gdocs/export", json={
            "chapter_id": chapter_id,
            "subtopic_id": subtopic_id,
            "force": False
        })
        assert resp.status_code == 409
        data = resp.json()["detail"]
        assert data["status"] == "conflict"
        assert data["gdoc_excerpt"] == "gdoc"
        assert data["spo_excerpt"] == "spo"
        assert data["last_export_at"] == "2026"


def test_unconfigured_bailout():
    """Missing service-account.json returns 503 instead of crashing."""
    with patch("routers.gdocs.get_auth_url", side_effect=GDocsNotConfiguredError("Not configured")):
        resp = client.get("/gdocs/auth")
        assert resp.status_code == 503
        assert "Not configured" in resp.json()["detail"]


# ── 7. Draft State & Sequence Validation ───────────────────────────────────────

def test_empty_chamber_export(tmp_spo_data_dir):
    """Attempting to export without a draft returns 404."""
    chapter_id = "chap_empty"
    subtopic_id = "sub_empty"
    
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }, thesis_id="")
    # Deliberately NOT writing a section draft
    
    resp = client.post("/gdocs/export", json={
        "chapter_id": chapter_id,
        "subtopic_id": subtopic_id
    })
    
    assert resp.status_code == 404
    assert "Save a draft first" in resp.json()["detail"]


# ── 8. Forced Overwrites & The Override Flag ───────────────────────────────────

def test_override_bypass(tmp_spo_data_dir):
    """Force=true payload bypasses conflict checks and successfully calls export."""
    chapter_id = "chap_force"
    subtopic_id = "sub_force"
    
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }, thesis_id="")
    storage.write_section_draft(chapter_id, subtopic_id, {"text": "Draft content"}, thesis_id="")
    
    with patch("routers.gdocs.export_subtopic", return_value={"status": "success"}) as mock_export:
        resp = client.post("/gdocs/export", json={
            "chapter_id": chapter_id,
            "subtopic_id": subtopic_id,
            "force": True
        })
        
        assert resp.status_code == 200
        assert resp.json() == {"status": "success"}
        mock_export.assert_called_once()
        # Verify force flag was passed down
        kwargs = mock_export.call_args.kwargs
        assert kwargs["force"] is True


# ── 9. Multi-Thesis Isolation (The Namespace Check) ────────────────────────────

def test_cross_contamination(tmp_spo_data_dir):
    """Router passes the thesis_id to storage, isolating workspaces."""
    chapter_id = "intro"
    subtopic_id = "hook"
    
    # Setup thesis_A
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }, thesis_id="thesis_A")
    storage.write_section_draft(chapter_id, subtopic_id, {"text": "Draft A"}, thesis_id="thesis_A")
    
    # Setup thesis_B
    storage.write_chapter(chapter_id, {
        "chapter_id": chapter_id,
        "subtopics": [{"subtopic_id": subtopic_id}]
    }, thesis_id="thesis_B")
    storage.write_section_draft(chapter_id, subtopic_id, {"text": "Draft B"}, thesis_id="thesis_B")
    
    with patch("routers.gdocs.export_subtopic", return_value={"status": "success"}) as mock_export:
        # Export for thesis_B
        resp = client.post("/gdocs/export?thesis_id=thesis_B", json={
            "chapter_id": chapter_id,
            "subtopic_id": subtopic_id
        })
        
        assert resp.status_code == 200
        mock_export.assert_called_once()
        kwargs = mock_export.call_args.kwargs
        # Verify thesis_B was passed and text B was read
        assert kwargs["thesis_id"] == "thesis_B"
        assert kwargs["draft_text"] == "Draft B"
