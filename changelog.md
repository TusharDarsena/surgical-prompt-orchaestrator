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

### Automated Source Card Indexing (Card 02b)
- **Automated Pipeline**: Implemented a fully autonomous pipeline (`source_index_service.py`) that uploads entire thesis folders to NotebookLM, generates scholarly index cards via specific prompts, and imports them directly into the Source Library.
- **Concurrency & Resiliency**: Built with rigorous in-memory mutexes (`asyncio.Lock`) and active task tracking (`asyncio.Task`) to prevent race conditions and allow true cancellation of running background jobs.
- **Batch Processing Guards**: Batch runs intelligently skip folders currently locked by concurrent single runs. Global authentication failures (`NLMAuthError`) abort the entire batch immediately instead of triggering rate limits.
- **Data Safety**: Implemented a 10MB file size guard and a partial-upload halt state (`waiting_for_manual_upload`). Raw NotebookLM JSON responses are backed up to local disk (`index_cards/`) *before* database import to prevent data loss on validation errors.
- **Production UI**: Added a new "Source Card Indexing" interface (Card 02b) featuring live polling, status chips with animations, confirmation modals for batch runs, and duplicate-prevention warnings with deep-links to existing library entries.

## [2026-05-27] - Drive-First Architecture (Decoupling Drive from Local Filesystem)

### Problem
SPO's source resolution pipeline was fragile because three independent systems (local scan, Drive, chapterization JSON) were coupled by a single human-readable folder name string. Any rename of a local folder or Drive folder broke the entire chain: `register-links` would silently skip the thesis, and `source_resolver.py` would return nothing, causing the NotebookLM pipeline to fail with no uploadable sources.

Root cause documented in `fragality.txt`. Resolution chain: `source_id` in chapterization JSON → scan dict key (local folder name) → `drive_links[filename]` → Drive URL → Drive file ID extracted by regex.

### Changed

**`spo_backend/services/storage.py`**
- Added `find_group_by_scan_key(scan_key, thesis_id="")`: looks up a source group by its `scan_key` field using the warm in-memory `_groups_cache`. O(n_groups), zero disk reads. Used by `source_resolver.py` to bypass the scan dict for Drive file ID resolution.

**`spo_backend/routers/drive.py`**
- Enhanced `_walk_drive_folder` (called by `POST /drive/register-links`): after writing `drive_links` to the scan dict (existing behavior, preserved for backward compat), now also writes `drive_file_id` directly onto each matching source record via `storage.write_source`. Response now includes `source_records_linked` count alongside `files_registered`.

**`spo_backend/services/source_resolver.py`**
- `resolve_source_files` is now **dual-mode**:
  - **Primary path (new):** calls `storage.find_group_by_scan_key`. If a group is found, file list and Drive file IDs are read directly from source records. No scan dict access required.
  - **Fallback path (legacy):** if no group is found (pre-migration data, or group not yet imported), falls back to the existing scan dict path unchanged.
  - Return dict now includes a `drive_file_id` field alongside `file_name` and `drive_link`.
  - All chapter-matching logic (`_split_chapter_references`, `_match_chapter_to_file`, `_WORD_TO_NUM`, `_ROMAN_TO_NUM`, all regex) is **completely unchanged**.

**`spo_backend/services/compiler_service.py`**
- `_resolve_required_sources` now passes `drive_file_id` through in both the resolved and unresolved return dicts. Previously dropped it silently.

**`spo_backend/services/notebooklm_service.py`**
- `_resolve_absolute_paths` now reads `drive_file_id` directly from the resolved entry when available (new path). Falls back to URL regex extraction (`/d/([a-zA-Z0-9_-]+)`) for legacy entries that only have `drive_link`. The `_match_thesis_name` lookup for local scan is still executed for local-mode uploads.

### NOT Changed
- `source_index_service.py` — unchanged. Its `_build_required_sources` runs before `do_auto_import` creates the group, so it must continue reading from the scan entry. Changing it would create a circular dependency.
- `source_importer.py` — unchanged.
- All Pydantic models — unchanged. The `PATCH /sources/groups/{group_id}/sources/{source_id}` dict merge pattern (`data.update(updates)`) preserves extra fields not in the Pydantic model, so `drive_file_id` is safe on source records without a model change.
- LLM prompts — unchanged. No UUID injection or CiteKey format changes.

### Migration
Zero downtime. Old groups (no `drive_file_id` on records) fall back to the legacy scan dict path automatically. New groups re-linked via `POST /drive/register-links` get `drive_file_id` written to source records and use the new primary path from that point forward.

