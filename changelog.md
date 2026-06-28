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

## [2026-06-25] - Prompt Compilation & Consistency Chain Refactor

### Added
- `CHAPTER CONTEXT`: The first two sentences of the chapter's arc are now automatically extracted and injected into the Stage 1 prompt.
- `CHAPTER_ID` for sources: Source citations in the prompt now append the chapter name/ID so NLM knows exactly which section of a document to reference.
- Consistency Chain workflow on Write Page: A manual "Ask NLM for Summary" step was added. Users now copy a pre-built summary request prompt, paste it into their NLM session, and paste the returned JSON back into Card 04 to save to the consistency chain.

### Changed
- **Pipeline Strategy Shift**: The automated Stage 2 (Gemini expansion) has been officially removed from the pipeline. The NLM Stage 1 draft is now considered the final draft. The second interaction with NLM is strictly for generating the consistency summary.
- `argument_structure` rendering: The compiler now correctly handles `argument_structure` as a JSON list, joining phases with newlines instead of rendering raw Python array strings.
- Subtopic Word Count: The `estimated_pages * 250` calculation logic was removed. The default target length is now strictly hardcoded to `~1500 words` (unless overridden).

### Removed
- `source_guidance`: The deprecated fallback field has been completely removed from both `source_resolver` and `compiler_service.py`. The pipeline now strictly expects `key_claim`.

### Fixed
- Fixed an `Uncaught TypeError: Cannot read properties of null` crash on the Write page by adding optional chaining (`?.`) to initialization event listeners.
- Fixed a NotebookLM auth crash by explicitly installing missing Playwright browser binaries (`playwright install chromium`).

---

## [2026-06-26] - Copy All Links Fix (Bharti Devi) & Source Resolution Strategy 4

### Root Cause Identified
The "Copy All Links" button was silently returning `null` for most sources in Bharti Devi's thesis
while working perfectly for Jitendra's. The asymmetry traced to a **`chapter_id` format difference**
in the two chapterization JSONs:
- **Jitendra**: `chapter_id = "History and Historiography in Fiction (Chapter 1)"` — the `(Chapter N)` suffix
  is parseable by `_extract_chapter_number`, so the resolver finds `05_chapter 1.pdf` ✅
- **Bharti Devi**: `chapter_id = "FEMINISM AND FEMINIST MOVEMENTS"` — a raw chapter heading with no number.
  `_match_chapter_to_file` found nothing → `drive_link = null` → source skipped by Copy All Links ❌

All three existing strategies (`_extract_chapter_number`, `_extract_keyword`, word-overlap) rely on
chapter numbers or keywords appearing in the filename body. When the `chapter_id` is a verbose heading
that doesn't map to a number, all three fail silently.

### Added
- **`_match_segment_by_chapter_title(segment, group_sources)`** in `source_resolver.py`:
  Strategy 4 matches the raw `chapter_id` string directly against `source.chapter_or_section`
  and `source.title` fields on source records. These fields are set during import from the
  NLM index card JSON and reflect the actual chapter heading (e.g. `"FEMINISM AND FEMINIST MOVEMENTS"`).
  Applied in **both** the primary path (group found via `find_group_by_scan_key`) and the legacy
  fallback path (group looked up via the matched scan dict key).
- **`scripts/fix_all_scan_keys.py`**: one-time repair script that fuzzy-matches group titles
  to drive scan keys across all theses and directly injects `drive_file_id` + `drive_link`
  into source records from the scan dict. Ran successfully: 31 scan_key fixes, 131 drive_file_id
  injections across both `t_1782417138270` (Bharti Devi) and `t_1782418619566` (Jitendra).

### Fixed
- **`registerDriveLinks` not sending `thesis_id`** (`source_library_api.js`, `api.js`):
  Both files called `_post("/drive/register-links", ...)` with a plain URL instead of `_p(...)`.
  `thesis_id` was never appended, so the backend searched the root `source_groups/` directory
  (empty — all theses are namespace-scoped under `theses/{thesis_id}/source_groups/`), injected
  nothing, and returned silently. Fixed by changing to `_post(_p("/drive/register-links"), ...)`.
- **All Jitendra source groups had `scan_key = ""`**: The previous session's `fix_null_scankeys.py`
  script only ran against Bharti Devi. Fixed by `fix_all_scan_keys.py` above.
- **5 Bharti Devi groups had no `drive_file_id`** on any source record despite having correct
  `scan_key`: consequence of the `thesis_id` bug above. Fixed by same repair script.

### Verified
Live API test against `t_1782417138270`:

```
ch1/1_1 → ch1/1_7: 25/25 links  [ALL OK]
ch2/2_1, 2_2, 2_3, 2_7: 17/17 links  [ALL OK]
GRAND TOTAL: 42/42 drive links resolved
```
