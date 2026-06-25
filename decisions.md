# Design Decisions — Surgical Prompt Orchestrator (SPO)

Each entry answers one question: *what must I never do / always do when touching this area?*
When making a design choice, check here first.

---

## 1. Scan Logic — Additive Storage

**Rule:** Never overwrite `drive_scan_result.json` wholesale. Always read → mutate in-place → write.

**Why:** Re-scanning must not destroy Drive links or import status from previous sessions. Entries are only removed when a folder is physically deleted from disk (guarded by `is_relative_to(scan_root)`).

**Enforcement:** All writes go through `_write_scan()` in `drive.py`, which always merges into the existing dict.

---

## 2. Drive Link Keys — Two-Tier Storage

**Rule:** `source_resolver.py` looks up `drive_file_id` from the source record first. The scan dict (`drive_links[filename]`) is a legacy fallback only.

**Why:** `register-links` now writes `drive_file_id` directly onto source records, decoupling resolution from the scan dict. The scan dict write is preserved for backward compat only.

**Enforcement:** `_walk_drive_folder` in `drive.py` writes to both; `source_resolver.py` reads from source records as primary.

---

## 4. Upload Method — Drive ID First, Local Path Fallback

**Rule:** When uploading PDFs to NLM, check `drive_file_id` first and use `client.sources.add_drive`. Fall back to `abs_path` + `client.sources.add_file`. Always implement both modes.

**Why:** Drive ID upload avoids local I/O and server-side file size constraints. Local fallback handles the case where `register-links` hasn't been run.

---

## 5. Notebook Lifecycle — Persistent, Never Temporary

**Rule:** Never design an NLM workflow that creates and deletes a notebook within a single job. Always store the notebook ID persistently and reuse it.

**Why:** Create-and-delete cycles risk NLM rate-limiting and produce orphaned notebooks on crashes. `source_index_service.py` stores `index_notebook_id` in the scan entry after creation and reuses it on every subsequent run.

---

## 6. Import Authority — `do_auto_import()` Only

**Rule:** Any code path that creates source records must call `do_auto_import()` in `services/source_importer.py`. Never write source records directly to storage.

**Why:** `do_auto_import` is the single normalization layer. Bypassing it allows schema drift between import paths — silently, with no errors at write time.

---

## 7. Batch State Storage

**Rule:** Use `storage.write_misc(f"batch_{batch_id}", data, thesis_id="")` for batch state. One file per batch run.

---

## 10. Google Docs Export

**10.1 OAuth Flow:** Use `google_auth_oauthlib.flow.Flow` (Web OAuth), not `InstalledAppFlow`. Redirect URI is set via `GDOCS_REDIRECT_URI` env var; default `http://localhost:8000/gdocs/auth/callback`.

**10.2 Token Storage:** OAuth tokens go to the OS keychain via `keyring`, with a plaintext JSON fallback on `keyring` failure.

**10.3 Named Range Update Ordering:** In a `batchUpdate`, always `insertText` first, then `deleteContentRange` of the now-shifted old text. Never reverse this order.

**Why:** The Docs API shifts indices on insert. Deleting first destroys the boundary markers, silently corrupting sync state.

**10.4 Conflict Detection:** Detect manual edits using **normalized string comparison** of Named Range text. Never use SHA-256 hashing or `revisionId`.

**Why:** SHA-256 produces constant false positives (Docs normalizes `\n` to `\x0b`). `revisionId` is document-level and produces cross-subtopic false positives.

**10.5 Chapter JSON — Read-Merge-Write:** All chapter JSON updates must read → mutate the specific keys → write. Never blindly overwrite.

**Why:** `storage.write_chapter()` does a full dict replacement. A blind write clobbers `gdoc_id` and other metadata not owned by the caller.

---

## 11. Two-Stage Scholarly Expansion

**11.1 Draft 1 as Source, Not Pasted Text:** Upload Draft 1 via `client.sources.add_text(wait=True)`. Never paste it into the chat input. Delete it in a `finally` block.

**Why:** NLM has undocumented chat input limits. Pasting a 2000+ word draft causes silent failures or hallucinations. The `finally` delete keeps the notebook under the 50-source limit.

**11.2 No `conversation_id` in Stage 2:** Stage 2 must always create a fresh chat thread. Never pass `conversation_id`.

**Why:** Reusing the Stage 1 thread contaminates the scholarly expansion with the base draft's generation context, causing ungrounded citations.

**11.3 Draft-First Persistence:** Commit Draft 1 to disk before starting Stage 2.

**Why:** Stage 2 is high-latency and timeout-prone. A Stage 2 crash must not lose valid Stage 1 work.

---

## 14. Drive-First Source Resolution

**14.1 `drive_file_id` Belongs on Source Records:** Store the raw Google Drive file ID as a first-class field on each source record (`source_id.json`). The scan dict `drive_links` is legacy only.

**14.2 `register-links` Is the Write Point:** `drive_file_id` is written to source records inside `POST /drive/register-links` (`_walk_drive_folder`). No separate endpoint.

**14.3 Dual-Mode Resolver with Explicit Fallback:** `source_resolver.resolve_source_files` uses source group records as primary and the scan dict as an explicit fallback. The fallback is reached only when `find_group_by_scan_key` returns `None`. It is clearly commented — never make it silent.

**14.4 `source_index_service.py` Is Deliberately Excluded from the New Path:** This service reads from the scan entry, not source records. Do not "fix" this.

**Why:** `_build_required_sources` runs at pipeline step 3, before `do_auto_import` is called at step 13. The source group does not exist in the database yet. Reading from source records at that point would be a circular dependency — the group can't exist before it's been imported.

**14.5 Multi-Thesis Note:** `find_group_by_scan_key` defaults `thesis_id=""` and it is not threaded through the compiler call chain. If per-thesis isolation in source resolution is ever needed, `thesis_id` must be threaded through `_resolve_required_sources → storage.resolve_source_files → source_resolver.resolve_source_files` at that point.

**14.6 Resolution Chain Fragility (Historical Context):** The old resolution chain was: `source_id` in chapterization JSON → scan dict key (local folder name) → `drive_links[filename]` → Drive URL → Drive file ID extracted by regex. This was fragile because three independent systems (local scan, Drive, chapterization JSON) were coupled by a single human-readable folder name string. Any rename of a local folder or Drive folder broke the entire chain: `register-links` would silently skip the thesis, and `source_resolver.py` would return nothing, causing the NotebookLM pipeline to fail with no uploadable sources. 

**14.7 Pydantic Models & Dict Merge:** The `PATCH /sources/groups/{group_id}/sources/{source_id}` dict merge pattern (`data.update(updates)`) preserves extra fields not in the Pydantic model, so adding `drive_file_id` is safe on source records without requiring a model change.

**14.8 Strategy 4 — Chapter Title Matching:** `source_resolver.py` now has a fourth resolution strategy: when Strategies 1–3 (chapter number extraction, keyword extraction, word-overlap) all fail, match the raw `chapter_id` string against `source.chapter_or_section` and `source.title` fields on the source records directly.

**Why this exists:** Chapterization JSONs generated from different thesis PDFs produce different `chapter_id` formats. If the thesis has verbose chapter headings without embedded numbers (e.g. `"FEMINISM AND FEMINIST MOVEMENTS"` instead of `"Chapter 2"`), Strategies 1–3 return nothing. Source records always carry `chapter_or_section` (set during NLM index card import), which is the verbatim heading — an exact normalised match against this field is reliable.

**Rule:** Never remove Strategy 4 on the assumption that "all theses will use chapter numbers." The format of `chapter_id` in the chapterization JSON is determined by how the LLM was prompted at chapterization time and is not under our control. Strategy 4 must remain active in **both** the primary path and the legacy scan fallback path.

**Historical note:** Bharti Devi's thesis (`t_1782417138270`) was the case that exposed this gap. All subtopics failed silently until Strategy 4 was added. 42/42 links resolved after the fix.

---

## 15. Frontend API Calls — Always Use `_p()` for Thesis-Scoped Endpoints

**Rule:** In all page-specific JS files, every `fetch`/`_post`/`_get` call that targets a
thesis-scoped backend endpoint MUST use `_p("/path/to/endpoint")` instead of the raw string
`"/path/to/endpoint"`. Never call `_post("/drive/register-links", ...)` — always `_post(_p("/drive/register-links"), ...)`.

**Why:** `_p()` (defined in `api.js` and `source_library_api.js`) appends `?thesis_id={activeThesisId}`
to the URL by reading from `localStorage.getItem("spo_active_thesis")`. Without it, `thesis_id`
defaults to `""` on the backend, causing all multi-thesis storage lookups to search the root
`source_groups/` directory (which is empty for thesis-namespaced setups). The failure is entirely
silent — the backend returns 200, injected nothing, and the frontend never gets drive links.

**Endpoints that are thesis-scoped and require `_p()`:** Everything under `/drive/`, `/sources/`,
`/compile/`, `/sections/`, `/consistency/`, `/notes/`, `/import/`, `/notebooklm/`.

**Enforcement:** Review any new frontend JS that calls a backend endpoint. If the endpoint
path is one of the above families, it must go through `_p()`. The raw string form is only
acceptable for truly global endpoints that have no `thesis_id` parameter (e.g. `/drive/local-files`
with no thesis scope, health checks, auth callbacks).
