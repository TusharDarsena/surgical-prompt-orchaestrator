# RULES.md — SPO Code Rules

> These rules exist because AI assistants sometimes produce code that looks right but causes real damage.
> This document is specific to SPO. Generic good-engineering advice is not in here.

---

## Rule 1 — Routers Handle HTTP, Services Handle Logic

The single most important structural rule. Routers translate domain exceptions to HTTP status codes. Services have no knowledge of HTTP.

```python
# ❌ WRONG — business logic inside a router
@router.post("/sources/groups/{group_id}/sources")
async def create_source(group_id: str, data: SourceCreate):
    source_id = f"src_{uuid4().hex[:8]}"
    path = DATA_DIR / "source_groups" / group_id / "sources" / f"{source_id}.json"
    with open(path, "w") as f:  # also violates Rule 6
        json.dump(source, f)

# ✅ RIGHT — router delegates to service
@router.post("/sources/groups/{group_id}/sources")
async def create_source(group_id: str, data: SourceCreate, thesis_id: str = ""):
    source = storage.write_source(group_id, f"src_{uuid4().hex[:8]}", data.model_dump(), thesis_id)
    if not source:
        raise HTTPException(status_code=404, detail="Group not found")
    return source
```

**Corollaries:**
- Services never import from `fastapi`.
- Routers never call `storage.*` functions directly — all persistence goes through a service.

---

## Rule 2 — The NLM Exception Contract Is Load-Bearing

The exception topology in `notebooklm_service.py` and `source_index_service.py` is not optional. Catching at the wrong level will either eat auth failures silently (batch hangs forever) or re-raise non-auth errors (batch crashes instead of continuing to the next job).

### In `_run_sequence` (`notebooklm_service`):
- `NLMAuthError` **must re-raise** — it escapes `_run_sequence` and is caught by `_run_batch_sequence`, which uses it to cancel the entire batch.
- `asyncio.CancelledError` **must re-raise** after writing `status: "cancelled"`.
- All other exceptions **must be caught inside `_run_sequence`**, written as `status: "error"` (or `"stage2_error"` if `status` is already `"expanding"`, meaning Stage 1 saved successfully), and **not re-raised**.

```python
# ✅ The exact pattern — do not change this topology
except NLMAuthError:
    raise  # batch needs this
except asyncio.CancelledError:
    state.update({"status": "cancelled", ...})
    storage.write_nlm_state(...)
    raise
except Exception as e:
    current_status = state.get("status", "running")
    final_status = "stage2_error" if current_status == "expanding" else "error"
    state.update({"status": final_status, "error": str(e)})
    storage.write_nlm_state(...)
    # do NOT raise
```

### In `run_index_sequence` (`source_index_service`):
The contract differs: **both** `NLMAuthError` and `NLMNotInstalledError` re-raise (batch must detect and abort). `asyncio.CancelledError` re-raises after writing `status: "cancelled"`. All other exceptions are caught and written as `status: "error"`. Do not merge the auth/install pair into a single bare `Exception` catch.

---

## Rule 3 — State Must Be Written to Disk at Every Pipeline Checkpoint

`_run_sequence` writes `nlm_state` to disk at six distinct points:

1. **Before anything** — `status: "running"`
2. After notebook create/reuse — `notebook_id` is persisted
3. After uploads — `sources_uploaded`, `sources_failed`
4. After Draft 1 saves + `add_text` — `status: "expanding"`, `draft_source_id`
5. After Draft 2 saves — `draft2_source_id`
6. At completion — `status: "done"`

Reorganising this function for clarity and collapsing or reordering those writes breaks the frontend's polling and leaves a crashed run with no recoverable trace. The length of this function is intentional. Each write is a checkpoint.

**The same principle applies to `run_index_sequence`** — it writes `_write_state` at every pipeline step through to completion.

---

## Rule 4 — Never Delete Locks From `_run_locks` or `_index_locks`

The `finally` block in `_run_sequence` is intentionally empty regarding the lock dict:

```python
finally:
    pass
    # Intentionally NOT deleting the lock from _run_locks to prevent the
    # Lock Deletion Race Condition. Idle locks consume virtually zero memory.
```

**Why:** Deleting a lock after a run creates a race where two coroutines each see "no lock" and both create new ones. The dictionary grows by at most one entry per unique `(chapter_id, subtopic_id)` pair ever run — effectively zero memory cost.

**Do not** add `_run_locks.pop(key, None)` or `_index_locks.pop(thesis_name, None)` to any `finally` block.

**This is different from `_active_tasks`.** The `finally` block in `run_index_sequence` **correctly** pops `_active_tasks[thesis_name]`. Task references must be cleaned up so `cancel_index_job` doesn't hold a reference to a completed task. Lock references must not be cleaned up. These are two different cleanup behaviors — do not treat them uniformly.

---

## Rule 5 — `asyncio.to_thread` Wraps Heavy Sync Work, Not Every Storage Call

`storage.py` is synchronous. Inside async functions, `asyncio.to_thread` is used for operations that do **substantial** synchronous work: filesystem scanning, multi-read helpers, large JSON reads/writes, and large text writes.

```python
# ✅ to_thread for heavy operations
prompts, required_sources = await asyncio.to_thread(_compile_prompt_data, ...)
resolved = await asyncio.to_thread(_resolve_absolute_paths, required_sources)
scan = await asyncio.to_thread(_read_scan)
await asyncio.to_thread(storage.write_section_draft, chapter_id, subtopic_id, data, thesis_id=thesis_id)
```

**Quick state checkpoint writes** — `storage.write_nlm_state`, `storage.write_batch_state`, `storage.read_batch_state` — are called directly throughout `_run_sequence` and `_run_batch_sequence`. They write small JSON blobs and do not need wrapping.

The rule is: if you are adding a call that iterates over files, reads or writes large data, or calls multiple storage functions in sequence, use `to_thread`. If you are writing a small state checkpoint, call it directly.

---

## Rule 6 — Never Bypass `_write()` for Persistence

`storage._write()` uses an atomic rename: write to `.tmp`, then `os.replace()` to the real path. This is the only crash-safety guarantee in a flat-file JSON system — a mid-write crash leaves a `.tmp` file, not a corrupted `.json`.

```python
# ❌ WRONG — bypasses crash safety
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f)

# ✅ RIGHT — always go through storage
storage.write_section_draft(chapter_id, subtopic_id, data, thesis_id=thesis_id)
```

Any new write path that opens a file directly instead of calling a `storage.write_*` function destroys the atomicity guarantee.

---

## Rule 7 — All NLM API Calls Must Go Through the Correct Semaphore

Two semaphores are defined in `notebooklm_service.py` and shared with `source_index_service.py`:

- `_chat_semaphore` (concurrency 5) — for `client.chat.ask`
- `_upload_semaphore` (concurrency 3) — for `client.sources.add_file`, `client.sources.add_drive`, `client.sources.add_text`

Every NLM API call in the codebase is guarded by one of these. Adding a new NLM call without the semaphore will silently work under light load and cause rate-limit failures under concurrent batch runs.

```python
# ✅ Chat — prefer _ask_with_retry for all pipeline prompt calls (handles retries + semaphore internally)
draft = await _ask_with_retry(client, notebook_id, prompt_1)

# ✅ Chat — direct call with semaphore only when you need custom error handling
async with _chat_semaphore:
    result = await client.chat.ask(notebook_id, summary_prompt)

# ✅ Upload — always wrap in _upload_semaphore with a timeout
async with _upload_semaphore:
    await asyncio.wait_for(client.sources.add_drive(notebook_id, ...), timeout=180.0)
```

---

## Rule 8 — NLM JSON Responses Must Be Cleaned Through `_clean_nlm_json`

NotebookLM sometimes wraps JSON in markdown fences and produces trailing commas, regardless of instructions. The canonical cleaning function is `_clean_nlm_json` in `source_index_service.py`.

```python
# ❌ WRONG — inline reimplementation
clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
parsed = json.loads(clean)

# ✅ RIGHT — use the shared function
from services.source_index_service import _clean_nlm_json
parsed = _clean_nlm_json(raw_answer)
```

Do not reimplement this inline. When NLM's output format drifts, there is one place to fix.

---

## Rule 9 — NLM Source Deduplication Key Is Filename-Without-Extension, Lowercased

NotebookLM strips file extensions from source titles. The dedup check uses:

```python
existing_filenames = {os.path.splitext(s.title)[0].lower() for s in existing_sources}
# then check:
if os.path.splitext(file_name)[0].lower() not in existing_filenames:
    # upload
```

Do not use `s.title == file_name`. `s.title` is `"Smith 2019"` and `file_name` is `"Smith 2019.pdf"` — naive equality causes double-uploads on every run for sources already in the notebook.

---

## Rule 10 — Do Not Split `notebooklm_service.py` or `storage.py`

Both files are intentionally large:
- `notebooklm_service.py` — the pipeline is a sequential state machine. The exception contract, semaphore definitions, and lock registry must remain co-located. Splitting them breaks the single-file dependency boundary that services/routers rely on.
- `storage.py` — the three caches are co-located intentionally. The invariant that a notes write never evicts the groups cache, and vice versa, depends on them sharing the same module scope. Splitting would silently break cache isolation.

If any other file is growing too large, flag it before touching anything.

---

## Rule 11 — All JS API Calls Go Through `api.js`; All Streamlit Calls Go Through `spo_frontend/api.py`

```javascript
// ❌ WRONG — fetch() called directly in a page JS file
const res = await fetch("/compile/notebooklm-prompt/ch1/st1");

// ✅ RIGHT
import { compilePrompt } from "./api.js";
const data = await compilePrompt("ch1", "st1", wordCount, styleNotes);
```

```python
# ❌ WRONG — requests called directly in a Streamlit page
import requests
r = requests.get(f"{BASE_URL}/thesis/chapters")

# ✅ RIGHT
import spo_frontend.api as api
chapters = api.list_chapters()
```

---

## Rule 12 — No Hardcoded Paths, URLs, or Credentials

```python
# ❌ WRONG
DATA_DIR = Path("C:/Users/TUSHAR/spo_data")
BASE_URL = "http://localhost:8000"

# ✅ RIGHT
DATA_DIR = Path(os.environ.get("SPO_DATA_DIR", Path.home() / "spo_data"))
BASE_URL = os.environ.get("SPO_API_URL", "http://localhost:8000")
```

Values that belong in `.env`: `SPO_DATA_DIR`, `SPO_API_URL`, `GOOGLE_SERVICE_ACCOUNT_FILE`, `SPO_NLM_EMAIL`, `SPO_NLM_PASSWORD`, `NOTEBOOKLM_AUTH_JSON`.

---

## Rule 13 — Changelog Guidelines

- **When to read it:** only when prompted explicitly
- **When to write it:** only when a session had some major changes that are worth writing. do not write a entry for a small changes.

---

## Checklist Before Every Task Is Complete

```
[ ] No direct open() writes — all persistence goes through storage.write_*()
[ ] Heavy async storage operations use asyncio.to_thread; quick state writes do not
[ ] NLM exception contract topology not changed (re-raise vs swallow, per-service rules)
[ ] Lock dict entries not deleted in finally blocks — _active_tasks.pop() is fine, lock dict pop is not
[ ] Every new NLM API call uses the correct semaphore (_chat or _upload)
[ ] NLM JSON parsing goes through _clean_nlm_json, not inline re.sub
[ ] No pip packages added without permission
[ ] Routers contain no business logic and do not call storage directly
[ ] Only touched files relevant to this task
```
