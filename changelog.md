# Changelog — Surgical Prompt Orchestrator (SPO)

All notable changes to this project will be documented in this file.
Each session: log what changed, what files were touched, and what was deliberately left alone.

---

## [2026-05-15] - Initial Session & Planning

### Added
- `changelog.md`, `decisions.md`, `implementation_plan.md` created.
- Planned: Automated Source Card JSON Batch Onboarding (Phase A: paste-back UI, Phase B: full NLM automation), `source_index_service.py`, refactor of `drive.py` and `source_library.js`.

---

## [2026-05-16] - NotebookLM Service Resilience & Drive Uploads

### Added
- Google Drive file upload as default source method (`client.sources.add_drive`). Local path upload remains as fallback.
- `waiting_for_manual_upload` state: batch jobs skip broken sources and continue; affected folder can be resumed independently after manual fix.

### Fixed
- Path traversal vulnerability in absolute path resolution.
- Duplicate uploads and premature 50-source limit crash (extension comparison and deduplication ordering).
- Global API semaphore replaced with separated semaphores (3 uploads, 5 chat).
- Memory leak in `_run_locks` cleanup.
- Blocking `os.path.isfile` call removed from async event loop.
- Trailing comma JSON decode errors from NotebookLM outputs.

---

## [2026-05-17] - Google Docs Export, Two-Stage Expansion, Source Card Indexing

### Added
- `gdocs` export service: append and in-place replace via Named Ranges, Safe Sync Guard (normalized string comparison for conflict detection), 409 Conflict diff modal, chapter-native `gdoc_id` tracking, Web OAuth 2.0 with `keyring` storage and `GDOCS_REDIRECT_URI` env var.
- Two-stage writing pipeline: Stage 1 base draft → Stage 2 scholarly expansion. Draft 1 committed to disk before Stage 2 begins. Draft 1 injected as a source via `client.sources.add_text` (not pasted into chat). Stage 2 always uses a fresh thread (no `conversation_id`). `stage2_error` status added. Force Unlock for jobs hung >10 mins.
- `source_index_service.py`: fully automated upload → prompt → import pipeline for thesis folders. Mutex locks, active task tracking, batch guards, 10MB file size limit, `waiting_for_manual_upload` halt, raw JSON backup to `index_cards/` before import.
- Card 02b UI: live polling, status chips, confirmation modals, duplicate-prevention warnings with deep-links.
- `pytest` suite: `tmp_path` sandbox for all storage tests, concurrency stress tests via `asyncio.gather`.

---

## [2026-05-27] - Drive-First Source Resolution

### Changed
- `storage.py`: added `find_group_by_scan_key(scan_key, thesis_id="")` — looks up source group by `scan_key` using in-memory `_groups_cache`, zero disk reads.
- `drive.py` (`_walk_drive_folder`): now also writes `drive_file_id` directly onto each matching source record after writing to scan dict. `register-links` response includes `source_records_linked` count.
- `source_resolver.py` (`resolve_source_files`): dual-mode — primary path reads file list and `drive_file_id` from source records via `find_group_by_scan_key`; fallback path uses scan dict unchanged. Return dict now includes `drive_file_id`.
- `compiler_service.py` (`_resolve_required_sources`): passes `drive_file_id` through in both resolved and unresolved return dicts.
- `notebooklm_service.py` (`_resolve_absolute_paths`): reads `drive_file_id` directly from resolved entry; falls back to regex extraction from `drive_link` URL for legacy entries.

### Not Changed
- `source_index_service.py` — `_build_required_sources` runs before `do_auto_import` creates the group; reading from source records at that point would be a circular dependency.
- `source_importer.py` — unchanged.
- All Pydantic models — `drive_file_id` is safe on source records without a model change due to the `data.update(updates)` dict merge pattern.
- LLM prompts — unchanged.

---