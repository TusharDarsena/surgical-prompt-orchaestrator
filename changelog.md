# Changelog — Surgical Prompt Orchestrator (SPO)

All notable changes to this project will be documented in this file.

## [2026-05-15] - Initial Session & Planning

### Added
- Created `changelog.md` to track session progress.
- Created `decisions.md` to document system design choices and reasoning.
- Created `implementation_plan.md` for "Automated Source Card JSON Batch Onboarding" feature.

### Planned
- Automated Source Card JSON Batch Onboarding:
  - Phase A: Prompt-helper with paste-back UI.
  - Phase B: Full NotebookLM automation (upload → prompt → import → cleanup).
- Refactoring `drive.py` and `source_library.js` to support the new indexing flow.
- New `source_index_service.py` for handling background indexing jobs.

## [2026-05-16] - NotebookLM Service Resilience & Drive Uploads

### Added
- Google Drive file uploads as the default source addition method (significantly faster, avoids timeouts). Local file upload remains as a fallback.
- `waiting_for_manual_upload` state: Process gracefully pauses instead of failing if sources are missing, allowing manual sync and seamless resumption.

note - Because of the way asyncio.gather and your workers are structured, if Worker A hits a missing source on Subtopic 1, it changes Subtopic 1's state to waiting_for_manual_upload and gracefully exits that specific run.

Worker A does not pause the whole batch! It immediately moves on to process Subtopic 2, 3, and 4.

This is actually the ideal production behavior. If you queue a batch of 20 subtopics overnight, and Subtopic #4 has a broken PDF link, you want the batch to finish the other 19 successfully. In the morning, you will see 19 subtopics marked done, and 1 marked waiting_for_manual_upload. You manually upload the PDF for that 1 subtopic, click your new "Resume" button, and it finishes the job independently.

Summary: The backend architecture is bulletproof. To make it a usable product, your next step should be moving to the frontend (spo_frontend/) to build out the UI state handling for this new pause/resume feature!

### Fixed
- Path traversal vulnerability in absolute path resolution.
- Duplicate uploads and premature 50-source limit crashes by correctly comparing extensions and calculating counts *after* deduplication.
- Global API semaphore bottleneck replaced with separated semaphores (3 for uploads, 5 for chat).
- Memory leak in `_run_locks` cleanup.
- Unnecessary blocking I/O (os.path.isfile) in the main async event loop.
- JSON decoding errors caused by trailing commas in NotebookLM outputs.

## [2026-05-17] - Google Docs Export Integration

### Added
- **Google Docs Export Service**: Implemented direct export of subtopic drafts to Google Docs.
- **Smart Appending & Replacing**: Subtopics are correctly appended to chapter-level Google Docs. Re-exporting an existing subtopic correctly replaces the existing text in-place using Google Docs Named Ranges.
- **Safe Sync Guard**: Implemented normalized string comparison to detect manual edits made in Google Docs. Protects user's manual edits from being overwritten accidentally, throwing a `409 Conflict`.
- **Conflict Resolution UI**: Added a side-by-side diff modal in the frontend to handle 409 Conflicts, allowing the user to either keep their Google Docs changes or force an overwrite with the new SPO draft.
- **Chapter-Native Document Tracking**: Google Doc IDs are now tracked natively within `chapter_XX.json` metadata, ensuring 1:1 mapping between SPO chapters and Google Docs.
- **Authentication**: Added Web OAuth 2.0 flow with `keyring` storage for secure token management, falling back to plaintext JSON where unavailable. Included `GDOCS_REDIRECT_URI` environment variable support for deployment flexibility.

### Two-Stage Scholarly Expansion (Prompt 2 Automation)
- **Automated Stage 2 Pipeline**: Implemented a fully autonomous two-stage writing pipeline. Stage 1 generates the base draft, and Stage 2 expands it using scholarly evidence.
- **Source-Based Expansion**: Replaced unreliable prompt concatenation (pasting Draft 1 into the chat) with server-side source injection via `client.sources.add_text`.
- **Atomic Draft Persistence**: The system now commits Draft 1 to storage *before* attempting expansion, ensuring work is never lost even if the LLM crashes.
- **Force Unlock**: Added a safety hatch for "zombie" NotebookLM runs. If a job hangs for >10 mins, users can force-unlock the subtopic, which triggers backend cleanup and state reset.
- **Error States**: Introduced `stage2_error` status to gracefully handle scholarly expansion failures without blocking the manual editor.

### Rigorous Backend Testing
- **Sandbox Testing Framework**: Implemented a complete `pytest` suite using `tmp_path` fixtures to verify storage operations, JSON serialization, and path resolution without touching production data.
- **Concurrency Verification**: Added stress tests to verify that `asyncio.Lock` properly serializes subtopic runs and prevents state-lock corruption.
- **Batch Resilience**: Verified that batch sequences correctly handle partial failures and authentication expiry.

