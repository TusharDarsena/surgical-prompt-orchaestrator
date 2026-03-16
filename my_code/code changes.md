Starting with the two new complete files, then the targeted changes to the two existing files.
the wo new files are which are already added to the project.


---Now the targeted changes to the two existing files.

---

### `routers/compiler.py` — 1 change

Replace the two function definitions with imports from the service. The function bodies are removed entirely since they now live in `compiler_service.py`. Everything else in `compiler.py` is untouched.

**Replace** (the `_resolve_required_sources` function definition + the `_render_notebooklm_prompt` function definition, which together span from the `# ── Source file resolver` comment to the end of the file):

```python
# ── Source file resolver ────────────────────────────────────────────────────────

def _resolve_required_sources(source_ids: list[dict]) -> list[dict]:
    ...

# ── Prompt renderer ────────────────────────────────────────────────────────────

def _render_notebooklm_prompt(
    ...
) -> dict[str, str]:
    ...
```

**With:**

```python
# ── Re-exported from service layer ────────────────────────────────────────────
# Imported here so existing callers of routers.compiler._resolve_required_sources
# and routers.compiler._render_notebooklm_prompt continue to work unchanged.

from services.compiler_service import _resolve_required_sources, _render_notebooklm_prompt  # noqa: F401
```

---

### `routers/notebooklm.py` — 7 changes

**Change 1 — Replace the entire imports block**

Old:
```python
import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from services import storage
from services.source_resolver import _match_thesis_name
```

New:
```python
import logging
import math
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from services import storage
from services.notebooklm_service import (
    NLMNotInstalledError,
    NLMAuthError,
    _nlm_client,
    is_run_active,
    _build_notebook_title,
    generate_batch_id,
    check_pdf_sizes,
    _run_sequence,
    _run_batch_sequence,
    suggest_summary_service,
)
```

---

**Change 2 — Remove the in-memory lock block and `_nlm_client`**

Delete everything from line 74 through line 141 (the `# ── In-memory run locks` block, `_run_locks`, `_locks_registry_lock`, `_get_run_lock`, and the entire `_nlm_client` context manager). These now live in the service.

---

**Change 3 — `get_nlm_status`: catch domain exceptions instead of `HTTPException`**

Old:
```python
    try:
        async with _nlm_client():
            pass
        return {"ok": True, "message": "NotebookLM client is ready."}
    except HTTPException as e:
        return {"ok": False, "message": e.detail}
```

New:
```python
    try:
        async with _nlm_client():
            pass
        return {"ok": True, "message": "NotebookLM client is ready."}
    except (NLMNotInstalledError, NLMAuthError) as e:
        return {"ok": False, "message": str(e)}
```

---

**Change 4 — `run_notebooklm`: use `is_run_active()` and `_build_notebook_title()`**

Old:
```python
    # ── Guard: no duplicate concurrent runs ───────────────────────────────
    run_lock = await _get_run_lock(chapter_id, subtopic_id)
    if run_lock.locked():
        raise HTTPException(
            status_code=409,
            detail=(
                f"A run is already in progress for '{subtopic_id}'. "
                "Poll GET /notebooklm/state to check progress."
            )
        )
```

New:
```python
    # ── Guard: no duplicate concurrent runs ───────────────────────────────
    if await is_run_active(chapter_id, subtopic_id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A run is already in progress for '{subtopic_id}'. "
                "Poll GET /notebooklm/state to check progress."
            )
        )
```

Old:
```python
    notebook_title = req.notebook_title or (
        f"SPO — {subtopic.get('number', subtopic_id)} {subtopic.get('title', '')}"
    )[:100]
```

New:
```python
    notebook_title = _build_notebook_title(subtopic, override=req.notebook_title)
```

---

**Change 5 — `get_nlm_state`: use `is_run_active()`**

Old:
```python
    run_lock = await _get_run_lock(chapter_id, subtopic_id)
    state = storage.read_nlm_state(chapter_id, subtopic_id)

    if not state:
        ...

    # If the lock is held but disk state says done/error (new run just
    # started while stale state was on disk), trust the in-memory lock.
    if run_lock.locked() and state.get("status") != "running":
        state["status"] = "running"
```

New:
```python
    active = await is_run_active(chapter_id, subtopic_id)
    state = storage.read_nlm_state(chapter_id, subtopic_id)

    if not state:
        ...

    # If the lock is held but disk state says done/error (new run just
    # started while stale state was on disk), trust the in-memory lock.
    if active and state.get("status") != "running":
        state["status"] = "running"
```

---

**Change 6 — `run_batch`: use `is_run_active()`, `generate_batch_id()`, `check_pdf_sizes()`**

Old:
```python
        run_lock = await _get_run_lock(chapter_id, sid)
        if run_lock.locked():
            raise HTTPException(
                status_code=409,
                detail=f"Subtopic '{sid}' already has a run in progress.",
            )
```

New:
```python
        if await is_run_active(chapter_id, sid):
            raise HTTPException(
                status_code=409,
                detail=f"Subtopic '{sid}' already has a run in progress.",
            )
```

Old:
```python
    # ── PDF size pre-check (resolve paths for all subtopics upfront) ──────────
    oversized: list[dict] = []
    for subtopic in validated:
        source_ids = subtopic.get("source_ids", [])
        from routers.compiler import _resolve_required_sources
        required_sources = await asyncio.to_thread(
            _resolve_required_sources, source_ids
        )
        resolved_paths = await asyncio.to_thread(
            _resolve_absolute_paths, required_sources
        )
        for entry in resolved_paths:
            size_mb = entry.get("file_size_mb")
            if size_mb is not None and size_mb > PDF_SIZE_LIMIT_MB:
                oversized.append({
                    "subtopic_id": subtopic["subtopic_id"],
                    "file": entry["file_name"],
                    "size_mb": size_mb,
                })

    if oversized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Batch blocked. {len(oversized)} PDF(s) exceed the {PDF_SIZE_LIMIT_MB} MB limit. "
                    "Split large PDFs into smaller files before running."
                ),
                "oversized_files": oversized,
            },
        )

    # ── Build batch_id and initial batch state ────────────────────────────────
    batch_id = f"batch_{chapter_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
```

New:
```python
    # ── PDF size pre-check (resolve paths for all subtopics upfront) ──────────
    oversized = await check_pdf_sizes(validated)
    if oversized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": (
                    f"Batch blocked. {len(oversized)} PDF(s) exceed the {PDF_SIZE_LIMIT_MB} MB limit. "
                    "Split large PDFs into smaller files before running."
                ),
                "oversized_files": oversized,
            },
        )

    # ── Build batch_id and initial batch state ────────────────────────────────
    batch_id = generate_batch_id(chapter_id)
```

Also add this import at the top of the `run_batch` endpoint (or just rely on the module-level import added in Change 1) — `PDF_SIZE_LIMIT_MB` is still referenced in the error message string. Add it to the service import line in Change 1:

```python
from services.notebooklm_service import (
    ...
    PDF_SIZE_LIMIT_MB,   # ← add this
    ...
)
```

---

**Change 7 — `get_batch_state`: use `is_run_active()`**

Old:
```python
        # Also check in-memory lock — a task might be running before first disk write
        run_lock = await _get_run_lock(chapter_id, sid)

        if state is None:
            status = "running" if run_lock.locked() else "pending"
        else:
            status = state.get("status", "pending")
            if run_lock.locked() and status != "running":
                status = "running"
```

New:
```python
        # Also check in-memory lock — a task might be running before first disk write
        active = await is_run_active(chapter_id, sid)

        if state is None:
            status = "running" if active else "pending"
        else:
            status = state.get("status", "pending")
            if active and status != "running":
                status = "running"
```

---

**Change 8 — `suggest_summary`: replace body with service delegation**

Old (everything after the four validation guards):
```python
    summary_prompt = (
        ...
    )

    try:
        async with _nlm_client() as client:
            result = await client.chat.ask(state["notebook_id"], summary_prompt)
        raw_text = result.answer
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NotebookLM API call failed: {e}")

    # Strip markdown fences ...
    suggested_summary = None
    parse_error = None
    try:
        clean = re.sub(r"```(?:json)?|```", "", raw_text).strip()
        suggested_summary = json.loads(clean)
    except (json.JSONDecodeError, ValueError) as e:
        parse_error = str(e)

    saved = False
    if req.save and suggested_summary and not parse_error:
        ...
        storage.write_section_summary(...)
        saved = True

    return { ... }
```

New:
```python
    try:
        return await suggest_summary_service(
            chapter_id=chapter_id,
            subtopic_id=subtopic_id,
            subtopic=subtopic,
            notebook_id=state["notebook_id"],
            save=req.save,
        )
    except (NLMNotInstalledError, NLMAuthError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
```

---

**Change 9 — Delete the three internal helpers at the bottom of `notebooklm.py`**

Delete entirely (lines 912 to end of file):
- `_compile_prompt_data`
- `_resolve_absolute_paths`

And also delete `PDF_SIZE_LIMIT_MB = 5.0` (line 547) since it's now in the service (and re-imported in Change 1).The two new files are above. Here's a summary of what to apply:

**New files (complete):** `compiler_service.py` and `notebooklm_service.py` as shown above.

**`routers/compiler.py` — 1 change:** Delete the two function bodies at the bottom, replace with `from services.compiler_service import _resolve_required_sources, _render_notebooklm_prompt`.

**`routers/notebooklm.py` — 9 changes, all surgical:**
- Slim the import block (remove `asyncio`, `json`, `os`, `re`, `contextlib`, `datetime`; add the service imports)
- Delete the lock block and `_nlm_client` (lines 74–141)
- 5 endpoint edits: swap `_get_run_lock().locked()` → `is_run_active()`, inline title builder → `_build_notebook_title()`, inline batch ID → `generate_batch_id()`, inline PDF size loop → `check_pdf_sizes()`, and `suggest_summary` body → `suggest_summary_service()`
- Delete `_compile_prompt_data`, `_resolve_absolute_paths`, and `PDF_SIZE_LIMIT_MB` from the bottom of the file