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

### Fixed
- Path traversal vulnerability in absolute path resolution.
- Duplicate uploads and premature 50-source limit crashes by correctly comparing extensions and calculating counts *after* deduplication.
- Global API semaphore bottleneck replaced with separated semaphores (3 for uploads, 5 for chat).
- Memory leak in `_run_locks` cleanup.
- Unnecessary blocking I/O (os.path.isfile) in the main async event loop.
- JSON decoding errors caused by trailing commas in NotebookLM outputs.
