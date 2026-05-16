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

| Path | Notebook | Duration | Used For |
|---|---|---|---|
| Draft Generation | Persistent, per subtopic | Long-lived (thesis project) | Writing Section |
| Source Indexing | Persistent, per thesis folder | Long-lived (reused on re-run) | Source Library Card 02b |

Both use `_nlm_client()` from `notebooklm_service.py`. Neither deletes notebooks automatically.

**Implication for new features:** If you add a third automation path, follow the same persistent-notebook pattern. Document it here.
