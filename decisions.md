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


### Rough text - core workflow about importing jsons in source library page - 
Looking at your codebase, here's the current JSON import flow for the Source Library:

**Where you make the JSONs**

You manually create `source.json` files locally. The schema is defined in `SourceImport` (source_importer.py) — one JSON per external work, containing work-level metadata plus a `chapters` array where each entry is an index card for one PDF.

**How you get them into SPO**

There are two paths, both ultimately hitting the same backend function:

**Path 1 — Direct file upload in the Source Library page (Card 01)**

You drag and drop `.json` files into the drop zone in `source_library.html`. The JS in `source_library.js` reads the file, parses it, and calls `API.importSourceJson()` from `source_library_api.js`, which POSTs to `POST /import/source`. The router in `importer.py` receives this and delegates entirely to `do_auto_import()` in `source_importer.py`. That function normalizes field names (via `_normalize_source_chapter`), validates with Pydantic, then writes a SourceGroup + Sources + IndexCards to disk.

**Path 2 — Drive Setup scan → save-index-card (Card 02)**

You scan a local folder (`POST /drive/scan-local`), which discovers PDF files grouped by parent folder and stores that tree. Then you paste a JSON into the "save index card" flow (`POST /drive/save-index-card`), which saves it to disk at `level2_path/index_cards/<thesis_name>.json` and also calls `do_auto_import()` internally.

**What `do_auto_import` does**

This is the single authority for all imports. It normalizes alternative field names (e.g. `filename` → `file_name`, `claims` → `key_claims`), validates via `SourceImport` Pydantic model, generates a `group_id`, writes one `group_meta.json`, and writes one `source_id.json` per chapter — with the index card embedded directly in the source file and `has_index_card: True` set immediately. No separate index card creation step needed.

**The normalization tolerance**

The importer deliberately accepts messy JSONs — it maps about a dozen alternative field names so that what NotebookLM produces doesn't need to exactly match the schema. Extra fields get swept into an `additional` column rather than causing failures.

**What's missing from the flow**

The `TEST_WORKFLOW.md` notes a missing prompt compiler endpoint (`GET /prompts/architect/...`), but that's since been replaced by `GET /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}` which reads from chapterization data rather than index cards. The index cards themselves are used only for the `suggested-sources` endpoint and as reference during writing — they're not directly injected into prompts anymore.

