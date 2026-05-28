# Design Decisions — Surgical Prompt Orchestrator (SPO)

This document records the architectural and design decisions for SPO.
It exists so that future features can be added without contradicting the existing setup.
When you are about to make a design choice, check here first.

---

## 1. Scan Logic — Additive Storage

**Decision:** `drive_scan_result.json` is updated **additively**. Entries are never wiped on re-scan.

**Reasoning:** Re-scanning must not destroy Drive links or import status that were registered in a previous session. Each scan pass only adds new folders and refreshes file lists for existing ones. An entry is only removed if its folder was physically deleted from disk (the `is_relative_to(scan_root)` guard prevents cross-thesis deletions on scoped scans).

**Enforcement:** All writes go through `_write_scan()` in `drive.py` which always merges into the existing dict, never replaces it.

**Implication for new features:** Never overwrite `drive_scan_result.json` wholesale. Always read → mutate in-place → write.

---

## 2. Drive Link Keys — PDF Filename

**Decision:** Google Drive links are keyed by the **PDF filename** (e.g. `sharma_2003_ch2.pdf`), not by Drive file ID.

**Reasoning:** Filenames are stable across local disk and Drive. The `Copy All Drive Links` feature needs to produce links that are predictable and reliable. File IDs are Drive-internal and change if files are re-uploaded; filenames don't.

**Enforcement:** `register_drive_links` in `drive.py` stores links under `thesis_entry["drive_links"][filename] = url`.

**Implication for new features:** When resolving which URL to use for a given PDF, always look up by filename, not by any Drive-side identifier.

---

## 3. UX Pattern — Run Table (Write Section Standard)

**Decision:** All long-running automation tasks that operate on a list of items use the **Run Table pattern** from `write_section.js`.

**Pattern:**
- One row per item (subtopic / thesis folder)
- Status badge: `idle → running → done / error`
- Per-row: `▶ Run`, `Re-run`, `Stop` buttons based on current status
- Batch button at top: `▶ Run All Idle/Unindexed`
- 3-second poller: `GET /status` → updates table in-place, no page reload
- On done: toast + downstream UI refreshes automatically

**Reasoning:** Users already understand this pattern from the Write Section. Consistent UX reduces cognitive load. The polling infrastructure is already proven and the CSS classes (`.run-row`, `.state-*`) are already written.

**Enforcement:** Any new automation card must match this layout and naming. Do not invent a new status display pattern.

---

## 4. Upload Method — Drive URL First, Local Path Fallback

**Decision:** For NLM automation, upload PDFs via **Drive URL if registered**, fall back to **local `abs_path`** if not.

**Reasoning:** Drive URL upload (`client.sources.add_url`) lets NLM fetch directly from Drive — no local I/O, no file size constraints from the server. Local path upload (`client.sources.add_file`) is the fallback for cases where Drive links haven't been registered. The scan entry always has `abs_path` available (via `folder_path` + filename), so the fallback is always available.

**Enforcement:** Source index service checks `drive_links[filename]` first. Falls back to `os.path.join(folder_path, filename)`. Both paths must be handled.

**Implication for new features:** Don't assume one upload path. Always implement both modes and select at runtime.

---

## 5. Notebook Lifecycle — Persistent, Not Temporary

**Decision:** NLM notebooks created for source card indexing are **persistent**, not temporary. One notebook per thesis folder. The notebook ID is stored in the scan entry and reused on re-runs.

**Reasoning:** Create-and-delete cycles risk NLM rate-limiting and produce orphaned notebooks if SPO crashes mid-job. The existing draft generation pattern (`_run_sequence` in `notebooklm_service.py`) already handles this correctly — it stores `notebook_id` and reuses it. We follow the same pattern for source indexing.

**Enforcement:** `source_index_service.py` stores `notebook_id` in `scan_entry["index_notebook_id"]` after creation. On every run, it checks for a stored ID and reuses if present.

**Implication for new features:** Never design NLM workflows that create and delete notebooks within a single job. Always store notebook IDs persistently.

---

## 6. Import Authority — `do_auto_import()` Only

**Decision:** `do_auto_import()` in `services/source_importer.py` is the **single authority** for creating source records from JSON.

**Reasoning:** Ensures that manual JSON imports and automated indexing results go through identical validation and storage logic. Prevents schema drift between import paths.

**Enforcement:** Both `drive.py/save_index_card` and the new `source_index_service.py` call `do_auto_import()` directly. No other code creates source records.

**Implication for new features:** If you need to import sources from any new path, always call `do_auto_import()`. Do not write source records directly to storage.

---

## 7. Batch State Storage — Per-Batch Files

**Decision:** Batch job state is written to **individual `misc/batch_{batch_id}.json` files**, one per batch run.

**Reasoning:** Mirrors the existing `storage.write_batch_state()` / `read_batch_state()` pattern used for draft generation. A single flat key for all jobs would create write-race conditions if two folders finish simultaneously, and would lose history across batches.

**Enforcement:** `source_index_service.py` uses `storage.write_misc(f"batch_{batch_id}", data)` for batch state. Per-folder progress lives in `scan_entry["index_job"]` sub-object.

---

## 8. Card Layout — Infrastructure vs Workflow

**Decision:** The Source Library cards are divided by **concern, not by feature**:
- **Card 02 — Drive Setup**: Scan folder only. Pure infrastructure — discovers PDFs on disk.
- **Card 02b — Source Card Indexing**: Drive link registration + indexing run table. Workflow — prepares and runs the automation.

**Reasoning:** The original layout placed Drive link registration in Card 02 (infrastructure) alongside the scan. This conflated two different concerns. Drive link registration is a prerequisite for URL-mode upload in source indexing — it belongs next to the feature that uses it. Users should see a clear sequence: scan (02) → register links if desired + run indexing (02b) → browse library (03).

**Enforcement:** `register-links` UI input field lives in Card 02b, not Card 02. Card 02 only exposes the `Scan Folder` action.

---

## 9. Two Paths for NLM Interaction

**Decision:** SPO has two distinct NLM automation paths with different notebook lifecycles:

| Path             | Notebook                      | Duration                      | Used For                |
| ---------------- | ----------------------------- | ----------------------------- | ----------------------- |
| Draft Generation | Persistent, per subtopic      | Long-lived (thesis project)   | Writing Section         |
| Source Indexing  | Persistent, per thesis folder | Long-lived (reused on re-run) | Source Library Card 02b |

Both use `_nlm_client()` from `notebooklm_service.py`. Neither deletes notebooks automatically.

**Implication for new features:** If you add a third automation path, follow the same persistent-notebook pattern. Document it here.

---

## 10. Google Docs Export Integration

**Decision 10.1: OAuth Flow & Deployment**
- **Decision:** Use the standard Web OAuth flow (`google_auth_oauthlib.flow.Flow`) with a manual `/gdocs/auth/callback` route, instead of `InstalledAppFlow`.
- **Reasoning:** `InstalledAppFlow` blocks the event loop and binds to localhost, which breaks if SPO is deployed to a remote server/VPS. The web flow supports both local and remote use cases seamlessly.
- **Enforcement:** The redirect URI is configurable via the `GDOCS_REDIRECT_URI` environment variable, defaulting to `http://localhost:8000/gdocs/auth/callback`.

**Decision 10.2: Token Storage**
- **Decision:** Store OAuth credentials securely in the OS keychain using the `keyring` library, with a plaintext fallback.
- **Reasoning:** Storing OAuth refresh tokens in plaintext JSON on disk (`spo_data/misc`) is a security risk. `keyring` provides zero-configuration secure storage on Windows/macOS/Linux. If `keyring` fails (e.g., headless environments), it falls back to plaintext JSON with a logged warning.

**Decision 10.3: Named Range Update Ordering**
- **Decision:** When updating a Named Range in Google Docs, the order of operations in the `batchUpdate` MUST be: 1. `insertText` at the original `startIndex`, 2. `deleteContentRange` of the old, shifted text.
- **Reasoning:** The Docs API shifts indices of all subsequent content when text is inserted. If you delete first, you lose the boundary markers. Reversing this order silently corrupts sync state.

**Decision 10.4: Conflict Detection (Safe Sync Guard)**
- **Decision:** Detect manual edits in Google Docs using normalized string comparison of the Named Range text, NOT raw SHA-256 hashing or document-level `revisionId`.
- **Reasoning:** Raw hashing produces constant false positives because Docs normalizes control characters (`\n` to `\x0b`) and whitespace. Document-level `revisionId` produces cross-subtopic false positives (editing subtopic B flags subtopic A). Normalized text comparison is the only accurate method.

**Decision 10.5: Chapter-Native Storage & Read-Merge-Write**
- **Decision:** Google Doc IDs (`gdoc_id`) are stored in the chapter metadata, and Named Range IDs (`gdoc_named_range_id`) in the subtopic metadata. All updates to chapter JSON MUST use a read-merge-write pattern.
- **Reasoning:** `storage.write_chapter()` performs a full dictionary replacement. Blindly writing back to the chapter will clobber the `gdoc_id` and other metadata.
- **Enforcement:** Services must always read the chapter, mutate the specific keys they own, and write it back.

---

## 11. Two-Stage Scholarly Expansion (Prompt 2)

**Decision 11.1: Source Injection vs. Prompt Concatenation**
- **Decision:** Do NOT paste Draft 1 into the LLM chatbox for Stage 2. Instead, upload it as a temporary text source via `client.sources.add_text(wait=True)`.
- **Reasoning:** NotebookLM has undocumented character limits on the chat input. Pasting a full Draft 1 (often 2000+ words) causes silent failures or hallucinations. Injecting it as a source ensures the LLM can query the full context without truncation.
- **Cleanup:** This source MUST be deleted in a `finally` block to keep the notebook within the 50-source limit.

**Decision 11.2: Thread Isolation for Evidence Integrity**
- **Decision:** Stage 2 must NEVER pass a `conversation_id`. Every scholarly expansion call creates a fresh chat thread.
- **Reasoning:** Reusing the Stage 1 thread contaminates the expansion with the base draft's generation logic. A fresh thread forces the LLM to look purely at the assigned sources and the newly injected Draft 1 source, ensuring citations are grounded in reality.

**Decision 11.3: Draft-First Atomic Persistence**
- **Decision:** The backend MUST commit Draft 1 to disk before starting the Stage 2 expansion.
- **Reasoning:** Stage 2 is high-latency and prone to API timeouts. If we wait for the full expansion to finish before saving, a Stage 2 crash loses the valid Stage 1 work. Saving first allows the user to recover the base draft even if scholarly expansion fails.

**Decision 11.4: Force Unlock Escape Hatch**
- **Decision:** Subtopics that have been in the `expanding` state for >10 minutes are eligible for a **Force Unlock**.
- **Reasoning:** Because `asyncio.Lock` is per-subtopic, a hung "expanding" process blocks all future attempts to fix that subtopic. Since server-side jobs can be orphaned by crashes, we provide a manual override that clears the backend lock and resets state.

---

## 12. Automated Testing Principles

**Decision 12.1: Sandbox File I/O (tmp_path)**
- **Decision:** All tests that touch `storage.py` or filesystem-dependent services MUST use the `tmp_path` fixture to override `SPO_DATA_DIR`.
- **Reasoning:** Mocking `storage` methods with in-memory dictionaries hides JSON serialization errors (e.g., non-serializable objects). Real file I/O against a temporary directory catches path resolution bugs and schema mismatches that mocks would miss.

**Decision 12.2: Concurrency Stress Testing**
- **Decision:** Every NLM service modification requires a concurrency test using `asyncio.gather`.
- **Reasoning:** The system relies on precise lock management (`_run_locks`). Manual testing cannot easily trigger race conditions. Automated tests ensure that multiple simultaneous requests for the same resource are correctly serialized.


## 13. Source Library & Indexing Workflow

This section outlines how external works (PDFs) and their corresponding scholarly index cards enter the SPO database. The core principle is that all paths ultimately delegate to a single authority for data normalization and storage.

### The Three Import Paths

**Path 1: Direct File Upload (Card 01 - Manual)**
The user drags and drops a manually created `.json` file into the UI. The frontend POSTs it to `/import/source`, where it is immediately handed to `do_auto_import()`.

**Path 2: Drive Setup Paste-back (Card 02 - Semi-Automated)**
After scanning a local or Drive folder (`/drive/scan-local`), the user manually prompts NotebookLM, copies the JSON response, and pastes it into the UI. The backend (`/drive/save-index-card`) saves a raw backup of the JSON to `index_cards/<thesis_name>.json` and then calls `do_auto_import()`.

**Path 3: Automated Source Indexing (Card 02b - Fully Automated)**
The system orchestrates the entire pipeline:
1. Gathers all PDFs for a scanned thesis folder.
2. Checks file sizes (rejecting >10MB) and NotebookLM capacity limits (max 50 sources).
3. Uploads PDFs to a dedicated NotebookLM notebook.
4. Pauses if files are missing (`waiting_for_manual_upload`), allowing the user to manually sync missing files and resume.
5. Queries the notebook using the standard `generate_source_json.txt` prompt.
6. Saves the raw JSON to disk as a backup *before* attempting database insertion.
7. Calls `do_auto_import()`.

### The Import Authority (`do_auto_import`)
`services/source_importer.py -> do_auto_import()` is the single source of truth for creating source records. 
- **Normalization Tolerance:** It acts as a "translation layer", mapping messy or hallucinated JSON keys (e.g., `filename` → `file_name`, `claims` → `key_claims`) to strict Pydantic models (`SourceImport`, `SourceChapterImport`).
- **Data Sweeping:** Unrecognized extra fields are not discarded; they are swept into an `additional` string field.
- **Storage:** It generates a `group_id`, writes one `group_meta.json`, and one `source_id.json` per chapter. Index cards are embedded directly inside the source file, setting `has_index_card: True` immediately.

### Automation Resiliency
The fully automated pipeline (Card 02b) is built with strict concurrency controls:
- **Mutex Locks & Active Tasks:** Background jobs are tracked via `asyncio.Lock` and `asyncio.Task` registries. This prevents double-clicks from spawning duplicate uploads and allows true cancellation by raising `CancelledError` inside the worker.
- **Batch Safe:** Batch runs intelligently skip folders that are currently locked by a concurrent single-run.
- **Fail-Safe Data:** If NotebookLM hallucinates a JSON structure that `do_auto_import` cannot parse, the pipeline crashes safely *after* writing the raw JSON backup to disk. The user loses zero API effort and can manually fix the JSON.

---

## 14. Drive-First Source Resolution Architecture

This section documents the architectural shift made on 2026-05-27 to decouple Drive file ID resolution from the local filesystem scan.

### The Problem Being Solved

The original architecture stored Drive file IDs inside the `drive_scan_result.json` scan dict, keyed by local folder name:

```
scan["My Thesis"]["drive_links"]["sharma_2003.pdf"] = "https://drive.google.com/..."
```

This created a three-way coupling: the chapterization JSON's `source_id` string, the local folder name in the scan dict, and the Drive folder name all had to match exactly. Any rename broke the entire pipeline.

### Decision 14.1: Drive File IDs Belong on Source Records, Not the Scan Dict

**Decision:** `drive_file_id` (the raw Google Drive file ID, e.g. `1A2B3Cxyz`) is stored directly on each source record (`source_id.json`) as a first-class field, alongside `file_name`.

**Reasoning:** Source records already have `file_name`. They are the natural home for the Drive-side identity of that file. Storing it in the scan dict instead forces the entire resolution chain to go through a string-keyed dict that is coupled to the local filesystem layout. Once `drive_file_id` lives on the source record, the scan dict is no longer needed for Drive-mode uploads.

**Enforcement:** `drive.py`'s `_walk_drive_folder` writes `drive_file_id` to each matching source record after writing to the scan dict. The scan dict write is preserved for backward compat.

**Implication for new features:** Never assume Drive file IDs are in `drive_links`. Always check `source_record.get("drive_file_id")` first, and treat `drive_links` as a legacy fallback.

---

### Decision 14.2: `register-links` Is the Write Point — No New Endpoint

**Decision:** `drive_file_id` is written to source records inside the existing `POST /drive/register-links` flow (`_walk_drive_folder`), not via a new endpoint.

**Reasoning:** Creating a new `link-source-group` endpoint (as an earlier plan proposed) would have downgraded UX: users would need to manually paste a Drive folder ID for every thesis group separately. The existing `register-links` already walks the entire Drive tree in one call. Piggy-backing the source record write onto the existing walk preserves the one-click UX.

**Enforcement:** `_walk_drive_folder` writes to both the scan dict (legacy) and source records (new) on every `register-links` call. Running `register-links` once is sufficient to activate the new resolution path.

---

### Decision 14.3: Dual-Mode Resolver with Explicit Fallback

**Decision:** `source_resolver.resolve_source_files` uses source group records as the primary path and the scan dict as an explicit, named fallback — never silently.

**Reasoning:** Zero-downtime migration requires both old (scan dict) and new (source records) data to work. A silent fallback risks hiding bugs. The fallback is reached only when `find_group_by_scan_key` returns `None`, which means the group either hasn't been imported yet or predates the new architecture. The code path is clearly commented.

**Enforcement:** The function has two explicit branches: a `if group:` block (primary) and a `if not group:` block (fallback). The fallback block reads from the scan dict with `_match_thesis_name` exactly as before. All chapter-matching logic (`_WORD_TO_NUM`, `_ROMAN_TO_NUM`, all regex) is shared between both paths.

---

### Decision 14.4: `source_index_service.py` Is Deliberately Excluded

**Decision:** The automated source card indexing pipeline (`source_index_service.py`) is **not** updated to read from source records. It continues reading from the scan entry.

**Reasoning:** `source_index_service._build_required_sources` runs *before* `do_auto_import` is called. The group does not exist in the database yet at that point — it is created by `do_auto_import` as step 13 of the pipeline. Attempting to read from the group at step 3 would be a circular dependency (group doesn't exist → `find_group_by_scan_key` returns `None` → crash). The scan entry is the only coherent data source for the pre-import upload phase.

**Enforcement:** `source_index_service.py` is not touched. Its `_build_required_sources` function continues reading `scan_entry["files"]` and `scan_entry["drive_links"]`.

---

### Decision 14.5: `find_group_by_scan_key` Uses `thesis_id=""`

**Decision:** `storage.find_group_by_scan_key` defaults `thesis_id` to `""` and `source_resolver.py` calls it without threading `thesis_id` through the compiler call chain.

**Reasoning:** The existing compiler pipeline already hardcodes `thesis_id=""` when reading `drive_scan_result.json`:
```python
scan = storage.read_misc("drive_scan_result", thesis_id="") or {}
```
Using the same default is consistent with the existing behavior. Threading `thesis_id` through `_resolve_required_sources` → `storage.resolve_source_files` → `source_resolver.resolve_source_files` would require cascading signature changes with no practical benefit for the current single-thesis usage pattern.

**Implication for new features:** If multi-thesis support ever requires per-thesis isolation in source resolution, `thesis_id` must be threaded through this call chain at that point. It is a known pre-existing limitation.

---

### The New Resolution Flow (End-to-End)

```
POST /drive/register-links (one click, same as before)
  └── _walk_drive_folder
        ├── writes to scan["My Thesis"]["drive_links"]      ← preserved for legacy
        └── writes drive_file_id onto each source record    ← NEW

Compile prompt for subtopic
  └── _resolve_required_sources (compiler_service.py)
        └── storage.resolve_source_files (storage.py re-export)
              └── source_resolver.resolve_source_files
                    ├── find_group_by_scan_key("My Thesis") → group found
                    │     ├── file list from group["sources"][*]["file_name"]
                    │     └── drive_file_id from group["sources"][?]["drive_file_id"]
                    └── [fallback] _match_thesis_name → scan dict

_resolve_required_sources returns:
  { source_id, chapter_id, file_name, drive_link, drive_file_id }  ← drive_file_id now included

notebooklm_service._resolve_absolute_paths
  ├── reads drive_file_id from entry directly (new)
  └── [fallback] regex extract from drive_link URL (legacy)

client.sources.add_drive(notebook_id, file_id=drive_file_id, ...)   ← direct ID, no regex
```
