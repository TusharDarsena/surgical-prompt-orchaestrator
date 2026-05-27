

### **I. Critical Architectural Blockers (Will Cause Crashes)**

* **The "Fatal Catch-22" in the Indexing Pipeline (`_build_required_sources`):** The plan suggests reading PDFs and Drive IDs directly from the database `group` instead of the `scan_entry` during indexing. This causes a circular dependency: `source_index_service.py`'s job is to read files to *create* the group. If it tries to read from a group to figure out what to upload, it will hit a `NoneType` error. The indexer must operate pre-import and rely on the scan dict.
* **`thesis_id` is Missing from the Resolver Call Chain (Signature Breakage):** The plan assumes you can drop `storage.find_group_by_scan_key(source_id, thesis_id)` directly into `source_resolver.py`. However, neither `resolve_source_files` nor its caller (`_resolve_required_sources`) accepts `thesis_id`. Threading this parameter through the compiler service layer requires multiple signature changes, entirely breaking the plan's "~15 lines changed" estimate.
* **The "Zero Downtime" Fallback is a Hard Crash:** The plan claims old groups will fall back to the old scan dict automatically. But its pseudocode directly accesses `group["sources"]`. If a legacy group is not found by `scan_key`, `group` is `None`, and `group["sources"]` instantly throws a `TypeError: 'NoneType' object is not subscriptable`. The required `if not group:` fallback block is completely missing.
* **Pydantic Model Data Loss on Updates:** `drive_file_id` is not in any existing Pydantic model (e.g., `SourceUpdateRequest`). If a user sends a `PATCH` request to update metadata via the UI, the dictionary merge pattern (`{k: v for k, v in req.model_dump().items() if v is not None}`) will silently wipe `drive_file_id` out of the JSON because the backend models don't know it exists.
* **Destruction of the Dynamic Local File Resolver:** The `scan-local` endpoint actively updates `scan[thesis_name]["files"]` when a new PDF is dropped into a local folder. If `source_resolver.py` is forced to only look at `group["sources"]`, the system goes blind to new PDFs added after the initial import.

---

### **II. Implementation Gaps & Missing Logic**

* **`_resolve_absolute_paths` Change is Incomplete/Inconsistent:** The plan doesn't clarify whether `source_resolver.py` outputs a raw `drive_file_id` or a full URL (`drive_link`). If it outputs a URL, `_resolve_absolute_paths` still needs its regex extraction (which the plan claims it is removing).
* **The `link-source-group` Endpoint Ignores Drive API Complexity:** Step 2 of the proposed endpoint says "Walk the Drive folder -> get {filename: drive_file_id}". This requires invoking `_get_drive_service()` and `_list_drive_files()`, handling missing Drive API credentials, matching filenames against source records, and writing the ID to each match. It is far more complex than the plan implies.
* **The `_groups_cache` Write-Back Contract is Omitted:** The plan suggests a wrapper over `storage.write_source`. It fails to note that `write_source` automatically calls `_evict_group(group_id, thesis_id)`. The implementer needs to know this so they don't add redundant cache-invalidation or assume the cache isn't stale post-write.
* **`find_group_by_scan_key` Has a Multi-Thesis Scope Bug:** `_groups_cache` is scoped to a single `thesis_id`. `drive_scan_result.json` is global. If a user has multiple thesis contexts, a `scan_key` like "My Thesis" could match a group in the wrong context. The plan assumes a 1:1 relationship that the data model doesn't strictly enforce.

---

### **III. Technical Debt & UX Limitations**

* **Workflow Downgrade (Manual Endpoint UX):** The current `POST /drive/register-links` recursively scans the entire base Drive directory and maps every folder it finds automatically (one-click sync). The new plan forces the user to manually copy-paste the specific Google Drive Folder ID for *every single thesis group* to a new endpoint. This is a massive step backward for user experience.
* **Change Count is Underestimated:** Beyond the `thesis_id` signature breakage, the estimate of "~5 lines" for `notebooklm_service.py` ignores the necessary fallback logic for legacy groups (those with a `drive_link` but no `drive_file_id`).