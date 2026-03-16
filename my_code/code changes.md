

## Change 1 — `write_section.py`

Remove the server-side chapter fetch entirely. Pass empty chapters so the template doesn't crash.

```python
# REMOVE the httpx import and the try/except chapter fetch block
# REPLACE the return with:

@router.get("/write-section", response_class=HTMLResponse)
async def write_section_page(request: Request):
    return templates.TemplateResponse(
        "write_section.html",
        {"request": request, "chapters": [], "api_base": _BACKEND},
    )
```

---

## Change 2 — `write_section.html`

**A)** Replace the script block at the top (remove `SPO_CHAPTERS` since chapters now load client-side):

```html
<!-- REPLACE the existing script block with: -->
<script>
  window.SPO_API_BASE = "{{ api_base }}";
  window.SPO_CHAPTERS = [];
</script>
```

Also remove the `<script id="spo-chapters-data">` tag entirely.

**B)** Add the thesis strip **just before** `<div class="context-strip">` inside `<main class="workspace">`:

```html
<!-- ── THESIS SELECTOR STRIP ── -->
<div class="thesis-strip">
  <span class="ts-label">Thesis</span>
  <div class="ts-select-wrap">
    <select id="writeThesisSelect">
      <option value="">Loading…</option>
    </select>
  </div>
</div>
```

---

## Change 3 — `api.js`

Add `_tid()` and `_p()` helpers right after the `const _delete` line, then update the affected exports:

```js
// ADD after the existing const _delete line:
function _tid() { return localStorage.getItem("spo_active_thesis") || ""; }
function _p(path) {
  const id = _tid();
  if (!id) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}thesis_id=${encodeURIComponent(id)}`;
}
```

Then update the exports — only the ones that are thesis-scoped:

```js
// REPLACE:
export const listChapters = () =>
  _get("/thesis/chapters");

// WITH:
export const listChapters = () =>
  _get(_p("/thesis/chapters"));
```

```js
// REPLACE:
export const compilePrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const qs = params.toString() ?
    `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};

// WITH:
export const compilePrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const tid = _tid();
  if (tid) params.set("thesis_id", tid);
  const qs = params.toString() ? `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};
```

```js
// REPLACE:
export const getDraft = (chapterId, subtopicId) =>
  _get(`/sections/${chapterId}/${subtopicId}/draft`);
export const saveDraft = (chapterId, subtopicId, text) =>
  _post(`/sections/${chapterId}/${subtopicId}/draft`, { text });
export const deleteDraft = (chapterId, subtopicId) =>
  _delete(`/sections/${chapterId}/${subtopicId}/draft`);

// WITH:
export const getDraft = (chapterId, subtopicId) =>
  _get(_p(`/sections/${chapterId}/${subtopicId}/draft`));
export const saveDraft = (chapterId, subtopicId, text) =>
  _post(_p(`/sections/${chapterId}/${subtopicId}/draft`), { text });
export const deleteDraft = (chapterId, subtopicId) =>
  _delete(_p(`/sections/${chapterId}/${subtopicId}/draft`));
```

```js
// REPLACE:
export const nlmRun = (chapterId, subtopicId, wordCount, styleNotes) => {
  const body = {};
  if (wordCount)  body.word_count              = wordCount;
  if (styleNotes) body.academic_style_notes     = styleNotes;
  return _post(`/notebooklm/run/${chapterId}/${subtopicId}`, body);
};
export const nlmState = (chapterId, subtopicId) =>
  _get(`/notebooklm/state/${chapterId}/${subtopicId}`);
export const nlmDeleteNotebook = (chapterId, subtopicId) =>
  _delete(`/notebooklm/notebook/${chapterId}/${subtopicId}`);
export const nlmRunBatch = (chapterId, subtopicIds, wordCount, styleNotes) => {
  const body = { subtopic_ids: subtopicIds };
  if (wordCount)  body.word_count           = wordCount;
  if (styleNotes) body.academic_style_notes = styleNotes;
  return _post(`/notebooklm/run-batch/${chapterId}`, body);
};

// WITH:
export const nlmRun = (chapterId, subtopicId, wordCount, styleNotes) => {
  const body = {};
  if (wordCount)  body.word_count           = wordCount;
  if (styleNotes) body.academic_style_notes = styleNotes;
  return _post(_p(`/notebooklm/run/${chapterId}/${subtopicId}`), body);
};
export const nlmState = (chapterId, subtopicId) =>
  _get(_p(`/notebooklm/state/${chapterId}/${subtopicId}`));
export const nlmDeleteNotebook = (chapterId, subtopicId) =>
  _delete(_p(`/notebooklm/notebook/${chapterId}/${subtopicId}`));
export const nlmRunBatch = (chapterId, subtopicIds, wordCount, styleNotes) => {
  const body = { subtopic_ids: subtopicIds };
  if (wordCount)  body.word_count           = wordCount;
  if (styleNotes) body.academic_style_notes = styleNotes;
  return _post(_p(`/notebooklm/run-batch/${chapterId}`), body);
};
```

```js
// REPLACE:
export const getChainForChapter = (chapterId) =>
  _get(`/consistency/${chapterId}`);
export const saveConsistencySummary = (chapterId, subtopicId, data) =>
  _post(`/consistency/${chapterId}/${subtopicId}`, data);
export const getPreviousSummary = (chapterId, subtopicId) =>
  _get(`/consistency/${chapterId}/previous-for/${subtopicId}`);

// WITH:
export const getChainForChapter = (chapterId) =>
  _get(_p(`/consistency/${chapterId}`));
export const saveConsistencySummary = (chapterId, subtopicId, data) =>
  _post(_p(`/consistency/${chapterId}/${subtopicId}`), data);
export const getPreviousSummary = (chapterId, subtopicId) =>
  _get(_p(`/consistency/${chapterId}/previous-for/${subtopicId}`));
```

Also the `generateConsistencyPrompt` function inside `api.js` already reuses `compilePrompt` — no extra change needed there since `compilePrompt` is already fixed above.

---

## Change 4 — `write_section.js`

**A)** Add thesis selector helpers right after the existing `const $ = id => ...` line:

```js
// ADD after `const $ = id => document.getElementById(id);`

// ── Thesis selector (same pattern as source_library.js) ──────────────────────
function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || "";
}

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem("spo_theses") || "[]"); } catch { return []; }
}

function loadWriteThesisSelector() {
  const sel = $("writeThesisSelect");
  if (!sel) return;
  const theses = _loadThesesIndex();
  const activeId = _activeThesisId();
  sel.innerHTML = "";
  if (!theses.length) {
    sel.innerHTML = `<option value="">— No theses —</option>`;
  } else {
    for (const t of theses) {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = `${t.title} — ${t.author}`;
      if (t.id === activeId) opt.selected = true;
      sel.appendChild(opt);
    }
  }
}

async function onWriteThesisChange(id) {
  localStorage.setItem("spo_active_thesis", id);
  // Reset chapter state and reload chapters for the new thesis
  state.chapters        = [];
  state.subtopics       = [];
  state.chapterId       = null;
  state.activeSubtopicId = null;
  state.runStates       = {};
  state.drafts          = {};
  state.sources         = [];
  state.chain           = [];
  state.batchId         = null;
  await loadChaptersFromServer();
}

async function loadChaptersFromServer() {
  try {
    const chapters = await API.listChapters();
    state.chapters = chapters ?? [];
    renderChapterSelect();
    const firstId = state.chapters[0]?.chapter_id ?? null;
    if (firstId) {
      $("chapterSelect").value = firstId;
      await actions.selectChapter(firstId);
    }
  } catch (err) {
    toast(`Failed to load chapters: ${err.message}`, "error");
  }
}

function renderChapterSelect() {
  const sel = $("chapterSelect");
  sel.innerHTML = "";
  if (!state.chapters.length) {
    sel.innerHTML = `<option value="">— No chapters —</option>`;
    return;
  }
  for (const ch of state.chapters) {
    const opt = document.createElement("option");
    opt.value = ch.chapter_id;
    opt.textContent = `Ch. ${ch.number} — ${ch.title}`;
    sel.appendChild(opt);
  }
}
```

**B)** In the `init()` function, replace the boot block at the bottom:

```js
// REPLACE:
  const firstChapterId = $("chapterSelect").value;
  if (firstChapterId) actions.selectChapter(firstChapterId);
}

// WITH:
  // ── Thesis selector ───────────────────────────────────────────────────────
  loadWriteThesisSelector();
  const writeThesisSel = $("writeThesisSelect");
  if (writeThesisSel) writeThesisSel.addEventListener("change", e => onWriteThesisChange(e.target.value));

  // ── Load chapters client-side (thesis-aware) ──────────────────────────────
  await loadChaptersFromServer();
}
```

Note `init()` must be `async function init()` for the `await` to work — change the function signature:

```js
// REPLACE:
function init() {

// WITH:
async function init() {
```

