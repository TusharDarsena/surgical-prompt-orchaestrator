"""
Google Docs Router
------------------
Exposes OAuth and export endpoints for the Google Docs integration.

Endpoints:
    GET  /gdocs/auth                 — Initiate OAuth flow (redirect to Google)
    GET  /gdocs/auth/callback        — Receive OAuth code, complete flow
    GET  /gdocs/auth/status          — { "connected": bool } for frontend polling
    POST /gdocs/export               — Export a subtopic draft to Google Docs
    GET  /gdocs/chapter/{chapter_id} — Return doc URL for a chapter (for UI link)
"""

import logging
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

from services import storage
from services.google_docs_service import (
    GDocsAuthError,
    GDocsConflictError,
    GDocsNotConfiguredError,
    complete_auth_flow,
    export_subtopic,
    get_auth_url,
    is_connected,
)

router = APIRouter(prefix="/gdocs", tags=["Google Docs"])
logger = logging.getLogger(__name__)


# ── Models ─────────────────────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    chapter_id: str
    subtopic_id: str
    force: bool = False


# ── Auth endpoints ─────────────────────────────────────────────────────────────


@router.get("/auth", summary="Initiate Google OAuth flow")
def initiate_auth():
    """
    Redirects the user to Google's OAuth consent screen.
    After login, Google redirects back to /gdocs/auth/callback.
    """
    try:
        auth_url = get_auth_url()
        return RedirectResponse(url=auth_url)
    except GDocsNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/auth/callback", summary="Handle Google OAuth callback")
def auth_callback(request: Request, code: str = Query(...), state: str = Query(...)):
    """
    Receives the authorization code from Google and completes the OAuth flow.
    Saves the token and closes the auth loop.
    """
    try:
        complete_auth_flow(code=code, state=state)
        # Return a minimal HTML page — the user can close this tab
        return {
            "status": "connected",
            "message": "Google account connected successfully. You can close this tab and return to SPO.",
        }
    except GDocsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error in OAuth callback")
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {e}")


@router.get("/auth/status", summary="Check if Google account is connected")
def auth_status():
    """Returns { connected: bool } — polled by the frontend after initiating auth."""
    return {"connected": is_connected()}


# ── Export endpoint ────────────────────────────────────────────────────────────


@router.post("/export", summary="Export a subtopic draft to Google Docs")
async def export_to_gdocs(req: ExportRequest, thesis_id: str = Query("")):
    """
    Exports the saved draft for a subtopic into the chapter's Google Doc.

    - Creates the chapter doc if it doesn't exist.
    - Appends if the subtopic has never been exported.
    - Replaces in-place if the Docs text matches the last export (no manual edits).
    - Returns 409 Conflict with gdoc_excerpt + spo_excerpt if manual edits are detected.
    - Re-sends with force=true to overwrite despite conflict.
    """
    # Fetch the chapter and subtopic metadata
    chapter = storage.read_chapter(req.chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{req.chapter_id}' not found.")

    chapter_title = chapter.get("title", req.chapter_id)

    subtopic_meta = next(
        (s for s in chapter.get("subtopics", []) if s.get("subtopic_id") == req.subtopic_id),
        None,
    )
    if subtopic_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subtopic '{req.subtopic_id}' not found in chapter '{req.chapter_id}'.",
        )

    subtopic_title = subtopic_meta.get("title", req.subtopic_id)

    # Fetch the saved draft
    draft = storage.read_section_draft(req.chapter_id, req.subtopic_id, thesis_id)
    if not draft or not draft.get("text"):
        raise HTTPException(
            status_code=404,
            detail=f"No saved draft found for subtopic '{req.subtopic_id}'. Save a draft first.",
        )

    draft_text: str = draft["text"]

    # Run the export
    try:
        result = await export_subtopic(
            thesis_id=thesis_id,
            chapter_id=req.chapter_id,
            chapter_title=chapter_title,
            subtopic_id=req.subtopic_id,
            subtopic_title=subtopic_title,
            draft_text=draft_text,
            force=req.force,
        )
        return result

    except GDocsConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "conflict",
                "gdoc_excerpt": e.gdoc_excerpt,
                "spo_excerpt": e.spo_excerpt,
                "last_export_at": e.last_export_at,
                "message": "Manual edits detected in Google Docs. Use force=true to overwrite.",
            },
        )
    except GDocsAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except GDocsNotConfiguredError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error exporting subtopic %s", req.subtopic_id)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")


# ── Chapter doc link ───────────────────────────────────────────────────────────


@router.get("/chapter/{chapter_id}", summary="Get Google Doc URL for a chapter")
def get_chapter_doc(chapter_id: str, thesis_id: str = Query("")):
    """
    Returns the Google Doc URL for a chapter, if one has been created.
    Used by the Write Section header to render the 'View Chapter Doc ↗' link.
    """
    chapter = storage.read_chapter(chapter_id, thesis_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")

    gdoc_id = chapter.get("gdoc_id")
    if not gdoc_id:
        return {"gdoc_id": None, "doc_url": None}

    return {
        "gdoc_id": gdoc_id,
        "doc_url": f"https://docs.google.com/document/d/{gdoc_id}/edit",
        "created_at": chapter.get("gdoc_created_at"),
    }
