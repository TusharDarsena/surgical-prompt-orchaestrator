/**
 * thesis_setup.js
 *
 * Multi-thesis selector (frontend-scoped — backend is single-synopsis).
 * Each thesis entry in localStorage holds:
 *   { id, title, author, synopsis, chapters[] }
 *
 * The active thesis drives all display. On switch, data is pulled fresh
 * from the backend for the matching synopsis/chapters.
 *
 * Inline edit pattern: .editing class on parent toggles .syn-val/.syn-input
 * and .ch-val/.ch-input pairs — zero layout shift, same DOM footprint.
 */

const BASE = window.SPO_API_BASE || "http://localhost:8000";

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function _req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

const API = {
  getSynopsis:   ()            => _req("GET",    "/thesis/synopsis"),
  putSynopsis:   (d)           => _req("PUT",    "/thesis/synopsis", d),
  patchSynopsis: (d)           => _req("PATCH",  "/thesis/synopsis", d),
  getChapters:   ()            => _req("GET",    "/thesis/chapters"),
  getChapter:    (id)          => _req("GET",    `/thesis/chapters/${id}`),
  patchChapter:  (id, d)       => _req("PATCH",  `/thesis/chapters/${id}`, d),
  deleteChapter: (id)          => _req("DELETE", `/thesis/chapters/${id}`),
  deleteSubtopic:(cid, sid)    => _req("DELETE", `/thesis/chapters/${cid}/subtopics/${sid}`),
  importThesis:  (d)           => _req("POST",   "/import/thesis", d),
  importChapterBulk: (d)       => _req("POST",   "/import/chapterization/bulk", d),
  importChapter: (id, d)       => _req("POST",   `/import/chapterization/${id}`, d),
};

// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  synopsis:  null,   // current synopsis object from backend
  chapters:  [],     // current chapters list from backend

  // Preview buffers (before confirm)
  synopsisPreview:  null,
  chapterPreview:   null,   // array of chapter objects parsed from JSON

  // UI flags
  synopsisLoaded: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ─────────────────────────────────────────────────────────────────────────────
// TOAST
// ─────────────────────────────────────────────────────────────────────────────

function toast(msg, type = "info", duration = 3500) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ─────────────────────────────────────────────────────────────────────────────
// CARD ACCORDION
// ─────────────────────────────────────────────────────────────────────────────

function toggleCard(id) {
  $(id).classList.toggle("active");
}

// ─────────────────────────────────────────────────────────────────────────────
// THESIS SELECTOR (multi-thesis frontend scoping)
// ─────────────────────────────────────────────────────────────────────────────

const THESES_KEY = "spo_theses";

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem(THESES_KEY) || "[]"); } catch { return []; }
}

function _saveThesesIndex(list) {
  localStorage.setItem(THESES_KEY, JSON.stringify(list));
}

function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || null;
}

function _setActiveThesis(id) {
  localStorage.setItem("spo_active_thesis", id);
}

function renderThesisSelector() {
  const sel = $("thesisSelect");
  const theses = _loadThesesIndex();
  const activeId = _activeThesisId();

  sel.innerHTML = "";

  if (!theses.length) {
    sel.innerHTML = `<option value="">— No theses yet — import synopsis_context.json to start —</option>`;
  } else {
    for (const t of theses) {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = `${t.title} — ${t.author}`;
      if (t.id === activeId) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  // Add "new thesis" option
  const newOpt = document.createElement("option");
  newOpt.value = "__new__";
  newOpt.textContent = "+ Import new thesis…";
  sel.appendChild(newOpt);
}

function _upsertThesisIndex(synopsis) {
  const theses = _loadThesesIndex();
  // Use title as stable key if no explicit id
  const id = synopsis._frontend_id || `t_${synopsis.title.slice(0, 20).replace(/\s+/g, "_")}`;
  const existing = theses.findIndex(t => t.id === id);
  const entry = { id, title: synopsis.title || "Untitled", author: synopsis.researcher || synopsis.author || "" };
  if (existing >= 0) theses[existing] = entry;
  else theses.push(entry);
  _saveThesesIndex(theses);
  _setActiveThesis(id);
  return id;
}

// ─────────────────────────────────────────────────────────────────────────────
// LOAD DATA
// ─────────────────────────────────────────────────────────────────────────────

async function loadAll() {
  await Promise.allSettled([loadSynopsis(), loadChapters()]);
}

async function loadSynopsis() {
  try {
    state.synopsis = await API.getSynopsis();
    state.synopsisLoaded = true;
    if (state.synopsis) _upsertThesisIndex(state.synopsis);
    renderSynopsis();
    renderThesisSelector();
    updateSynopsisPill();
  } catch (_) {
    state.synopsis = null;
    state.synopsisLoaded = true;
    renderSynopsis();
    updateSynopsisPill();
  }
}

async function loadChapters() {
  const list = $("chapterList");
  list.innerHTML = `<div class="chapters-loading">Loading chapters</div>`;
  try {
    // Fetch full chapter data for each chapter (with subtopics)
    const summaries = await API.getChapters();
    const full = await Promise.all(summaries.map(c => API.getChapter(c.chapter_id)));
    state.chapters = full.filter(Boolean).sort((a, b) => (a.number ?? 0) - (b.number ?? 0));
    renderChapters();
    updateChaptersPill();
  } catch (err) {
    list.innerHTML = `<div class="chapters-empty">Failed to load chapters: ${esc(err.message)}</div>`;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SYNOPSIS RENDER + INLINE EDIT
// ─────────────────────────────────────────────────────────────────────────────

function renderSynopsis() {
  const block = $("synopsisBlock");
  const syn = state.synopsis;

  if (!syn) {
    block.innerHTML = `<div class="synopsis-empty">No synopsis yet. Import synopsis_context.json below.</div>`;
    return;
  }

  // Resolve fields — backend stores different field names depending on import path
  const title       = syn.title || "";
  const author      = syn.researcher || syn.author || "";
  const field       = syn.field || "";
  const scope       = syn.temporal_scope || syn.scope_and_limits || "";
  const frameworks  = Array.isArray(syn.methodology?.theoretical_frameworks)
    ? syn.methodology.theoretical_frameworks.join(", ")
    : (syn.theoretical_frameworks || "");
  const themes      = Array.isArray(syn.central_themes)
    ? syn.central_themes.join(", ")
    : (syn.themes || "");
  const argument    = syn.core_argument || syn.central_argument || "";

  block.innerHTML = `
    <div class="synopsis-block-header">
      <span class="synopsis-block-label">Current Synopsis</span>
      <div class="synopsis-block-actions">
        <button class="icon-btn" id="synEditBtn" title="Edit inline" onclick="toggleSynEdit()">✏</button>
      </div>
    </div>

    <div class="syn-grid">
      <div class="syn-field">
        <span class="syn-field-label">Title</span>
        <span class="syn-val">${esc(title)}</span>
        <input class="syn-input" type="text" data-field="title" value="${esc(title)}"/>
      </div>
      <div class="syn-field">
        <span class="syn-field-label">Author</span>
        <span class="syn-val">${esc(author)}</span>
        <input class="syn-input" type="text" data-field="author" value="${esc(author)}"/>
      </div>
      <div class="syn-field">
        <span class="syn-field-label">Field</span>
        <span class="syn-val">${esc(field)}</span>
        <input class="syn-input" type="text" data-field="field" value="${esc(field)}"/>
      </div>
      <div class="syn-field">
        <span class="syn-field-label">Temporal Scope</span>
        <span class="syn-val">${esc(scope)}</span>
        <input class="syn-input" type="text" data-field="temporal_scope" value="${esc(scope)}"/>
      </div>
      <div class="syn-field">
        <span class="syn-field-label">Theoretical Frameworks</span>
        <span class="syn-val">${esc(frameworks)}</span>
        <input class="syn-input" type="text" data-field="frameworks" value="${esc(frameworks)}"/>
      </div>
      <div class="syn-field">
        <span class="syn-field-label">Central Themes</span>
        <span class="syn-val">${esc(themes)}</span>
        <input class="syn-input" type="text" data-field="themes" value="${esc(themes)}"/>
      </div>
    </div>

    <div class="syn-argument-row">
      <span class="syn-field-label">Central Argument</span>
      <div class="syn-argument-val">${esc(argument)}</div>
      <textarea class="syn-argument-input" data-field="core_argument">${esc(argument)}</textarea>
    </div>

    <div class="syn-edit-actions">
      <button class="btn btn-primary" style="padding:6px 14px;" onclick="saveSynEdit()">Save</button>
      <button class="btn btn-ghost"   style="padding:6px 14px;" onclick="cancelSynEdit()">Cancel</button>
    </div>
  `;
}

window.toggleSynEdit = function() {
  const block = $("synopsisBlock");
  const btn   = $("synEditBtn");
  block.classList.toggle("editing");
  if (btn) btn.classList.toggle("active");
};

window.saveSynEdit = async function() {
  const block = $("synopsisBlock");
  const patch = {};

  // Collect all changed syn-input values
  block.querySelectorAll(".syn-input[data-field]").forEach(inp => {
    patch[inp.dataset.field] = inp.value;
  });
  const argTa = block.querySelector(".syn-argument-input[data-field]");
  if (argTa) patch[argTa.dataset.field] = argTa.value;

  // Map flat patch fields back to backend shape
  const backendPatch = {
    title:          patch.title,
    temporal_scope: patch.temporal_scope,
    field:          patch.field,
    core_argument:  patch.core_argument,
    central_themes: patch.themes ? patch.themes.split(",").map(s => s.trim()).filter(Boolean) : undefined,
  };
  // researcher/author
  if (patch.author) backendPatch.researcher = patch.author;

  try {
    await API.patchSynopsis(backendPatch);
    toast("Synopsis saved", "success");
    block.classList.remove("editing");
    await loadSynopsis();
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
};

window.cancelSynEdit = function() {
  $("synopsisBlock").classList.remove("editing");
  const btn = $("synEditBtn");
  if (btn) btn.classList.remove("active");
};

// ─────────────────────────────────────────────────────────────────────────────
// SYNOPSIS IMPORT (with preview)
// ─────────────────────────────────────────────────────────────────────────────

async function onSynopsisFile(files) {
  if (!files.length) return;
  const file = files[0];
  try {
    const text = await file.text();
    state.synopsisPreview = JSON.parse(text);
    renderSynopsisPreview();
    $("synPreview").style.display = "block";
    toast("synopsis_context.json loaded — review and confirm", "info");
  } catch (err) {
    toast(`Invalid JSON: ${err.message}`, "error");
  }
}

function renderSynopsisPreview() {
  const p = state.synopsisPreview;
  if (!p) return;
  const author = p.researcher || p.author || "—";
  const arg    = p.core_argument || p.central_argument || "—";
  $("pvSynTitle").textContent  = p.title || "—";
  $("pvSynAuthor").textContent = author;
  $("pvSynField").textContent  = p.field || "—";
  $("pvSynScope").textContent  = p.temporal_scope || "—";
  $("pvSynArg").textContent    = arg;
}

window.confirmSynImport = async function() {
  if (!state.synopsisPreview) return;
  try {
    await API.importThesis(state.synopsisPreview);
    toast("Synopsis imported", "success");
    $("synPreview").style.display = "none";
    state.synopsisPreview = null;
    await loadSynopsis();
    // Mark card as done
    $("card01").classList.remove("active");
    $("card01").classList.add("done");
  } catch (err) {
    toast(`Import failed: ${err.message}`, "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// CHAPTERS RENDER + INLINE EDIT
// ─────────────────────────────────────────────────────────────────────────────

function renderChapters() {
  const list = $("chapterList");
  list.innerHTML = "";

  if (!state.chapters.length) {
    list.innerHTML = `<div class="chapters-empty">No chapters yet. Import chapterization.json above.</div>`;
    updateChaptersPill();
    return;
  }

  for (const ch of state.chapters) {
    list.appendChild(_buildChapterRow(ch));
  }
  updateChaptersPill();
}

function _buildChapterRow(ch) {
  const cid = ch.chapter_id;
  const subtopics = ch.subtopics || [];
  const hasArc = Boolean(ch.chapter_arc);
  const arcLabel = hasArc ? "Arc set" : "⚠ Arc missing";

  const row = document.createElement("div");
  row.id = `ch-${cid}`;
  row.className = `chapter-row${hasArc ? " has-arc" : ""}`;

  row.innerHTML = `
    <div class="chapter-header" onclick="_toggleChapter('ch-${cid}')">
      <span class="chapter-num">Ch.${esc(String(ch.number ?? ""))}</span>
      <div class="chapter-title-block">
        <div class="ch-title-val">${esc(ch.title)}</div>
        <input class="ch-title-input" type="text" value="${esc(ch.title)}" onclick="event.stopPropagation()"/>
        <div class="chapter-sub">${subtopics.length} subtopic${subtopics.length !== 1 ? "s" : ""} · ${arcLabel}</div>
      </div>
      <div class="chapter-actions">
        <button class="icon-btn" title="Edit" onclick="_toggleChEdit('ch-${cid}', event)">✏</button>
        <button class="icon-btn danger" title="Delete" onclick="_confirmDeleteChapter('${cid}', 'ch-${cid}', event)">🗑</button>
      </div>
      <span class="chapter-chevron">▾</span>
    </div>

    <div class="chapter-body">

      <div class="ch-field">
        <div class="ch-field-label">Goal</div>
        <div class="ch-val">${esc(ch.goal || "")}</div>
        <textarea class="ch-input" rows="2" onclick="event.stopPropagation()">${esc(ch.goal || "")}</textarea>
      </div>

      <div class="ch-field">
        <div class="ch-field-label">Chapter Arc</div>
        ${hasArc
          ? `<div class="arc-val">${esc(ch.chapter_arc)}</div>
             <textarea class="arc-input" onclick="event.stopPropagation()">${esc(ch.chapter_arc)}</textarea>`
          : `<div class="arc-missing">⚠ No arc set — re-import chapterization.json or click ✏ to add manually.</div>
             <textarea class="arc-input" placeholder="150–200 words describing how all subtopics connect argumentatively…" onclick="event.stopPropagation()"></textarea>`
        }
      </div>

      <div class="ch-edit-actions">
        <button class="btn btn-primary" style="padding:6px 14px;"
          onclick="_saveChEdit('${cid}', 'ch-${cid}')">Save</button>
        <button class="btn btn-ghost" style="padding:6px 14px;"
          onclick="_cancelChEdit('ch-${cid}')">Cancel</button>
      </div>

      <div class="subtopic-list">
        <div class="sub-list-label">Subtopics</div>
        ${subtopics.map(sub => `
          <div class="subtopic-row" id="sub-${sub.subtopic_id}">
            <span class="sub-num">${esc(sub.number)}</span>
            <div class="sub-body">
              <div class="sub-title">${esc(sub.title)}</div>
              ${sub.goal ? `<div class="sub-goal">${esc(sub.goal)}</div>` : ""}
              ${sub.position_in_argument ? `<div class="sub-pos">${esc(sub.position_in_argument)}</div>` : ""}
              ${sub.source_ids?.length ? `<div class="sub-sources">${sub.source_ids.length} source entr${sub.source_ids.length === 1 ? "y" : "ies"}</div>` : ""}
            </div>
            <button class="icon-btn danger" style="margin-top:2px;"
              title="Delete subtopic"
              onclick="event.stopPropagation(); _confirmDeleteSubtopic('${cid}', '${sub.subtopic_id}')">🗑</button>
          </div>
        `).join("")}
        ${subtopics.length === 0 ? `<div style="color:var(--muted);font-size:12px;font-style:italic;padding:8px 0;">No subtopics — import chapterization.json to add them.</div>` : ""}
      </div>

      <!-- Add subtopic manually -->
      <div style="margin-top:10px;">
        <button class="btn btn-ghost" style="padding:5px 12px;font-size:11.5px;"
          onclick="_toggleEl('addsub-${cid}')">+ Add Subtopic</button>
        <div class="add-sub-form" id="addsub-${cid}" style="display:none;">
          <div class="add-sub-label">Add Subtopic</div>
          <div class="add-sub-grid">
            <div class="form-group"><label class="form-label">Number ★</label><input type="text" id="snum-${cid}" placeholder="1.3.2"/></div>
            <div class="form-group"><label class="form-label">Title ★</label><input type="text" id="stitle-${cid}" placeholder="Subtopic title"/></div>
          </div>
          <div class="form-group" style="margin-bottom:8px;">
            <label class="form-label">Goal ★</label>
            <textarea id="sgoal-${cid}" style="min-height:56px;" placeholder="What must this subtopic argue or establish?"></textarea>
          </div>
          <div class="form-group" style="margin-bottom:10px;">
            <label class="form-label">Position in Argument <span style="font-weight:400;text-transform:none;">(optional)</span></label>
            <input type="text" id="spos-${cid}" placeholder="e.g. Establishes the problem to be solved."/>
          </div>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" style="padding:6px 14px;" onclick="_addSubtopic('${cid}')">Add</button>
            <button class="btn btn-ghost"   style="padding:6px 14px;" onclick="_toggleEl('addsub-${cid}')">Cancel</button>
          </div>
        </div>
      </div>

    </div>
  `;

  return row;
}

// ── Chapter accordion ──────────────────────────────────────────────────────

window._toggleChapter = function(id) {
  $(id).classList.toggle("open");
};

window._toggleChEdit = function(id, e) {
  e.stopPropagation();
  const row = $(id);
  row.classList.toggle("editing");
  row.classList.add("open"); // always open body when editing
};

window._cancelChEdit = function(id) {
  $(id).classList.remove("editing");
};

window._saveChEdit = async function(chapterId, rowId) {
  const row = $(rowId);
  const title   = row.querySelector(".ch-title-input")?.value ?? "";
  const goal    = row.querySelector(".ch-input")?.value ?? "";
  const arc     = row.querySelector(".arc-input")?.value ?? "";

  try {
    await API.patchChapter(chapterId, {
      title:       title  || undefined,
      goal:        goal   || undefined,
      chapter_arc: arc    || undefined,
    });
    toast("Chapter saved", "success");
    row.classList.remove("editing");
    await loadChapters();
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
};

window._confirmDeleteChapter = function(chapterId, rowId, e) {
  e.stopPropagation();
  if (!confirm("Delete this chapter and all its subtopics?")) return;
  API.deleteChapter(chapterId).then(() => {
    const el = $(rowId); if (el) el.remove();
    state.chapters = state.chapters.filter(c => c.chapter_id !== chapterId);
    updateChaptersPill();
    toast("Chapter deleted", "success");
  }).catch(err => toast(`Delete failed: ${err.message}`, "error"));
};

window._confirmDeleteSubtopic = function(chapterId, subtopicId) {
  if (!confirm("Delete this subtopic?")) return;
  API.deleteSubtopic(chapterId, subtopicId).then(() => {
    const el = $(`sub-${subtopicId}`); if (el) el.remove();
    // Update in-memory
    const ch = state.chapters.find(c => c.chapter_id === chapterId);
    if (ch) ch.subtopics = ch.subtopics.filter(s => s.subtopic_id !== subtopicId);
    updateChaptersPill();
    toast("Subtopic deleted", "success");
  }).catch(err => toast(`Delete failed: ${err.message}`, "error"));
};

window._addSubtopic = async function(chapterId) {
  const num   = $(`snum-${chapterId}`)?.value.trim();
  const title = $(`stitle-${chapterId}`)?.value.trim();
  const goal  = $(`sgoal-${chapterId}`)?.value.trim();
  const pos   = $(`spos-${chapterId}`)?.value.trim();

  if (!num || !title || !goal) { toast("Number, Title and Goal are required", "error"); return; }

  try {
    await _req("POST", `/thesis/chapters/${chapterId}/subtopics`, {
      number: num, title, goal,
      position_in_argument: pos || null,
    });
    toast(`Added subtopic ${num}`, "success");
    _toggleEl(`addsub-${chapterId}`);
    await loadChapters();
  } catch (err) {
    toast(`Add failed: ${err.message}`, "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// CHAPTER IMPORT (with preview)
// ─────────────────────────────────────────────────────────────────────────────

async function onChapterFile(files) {
  if (!files.length) return;
  const file = files[0];
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    state.chapterPreview = Array.isArray(parsed) ? parsed : [parsed];
    renderChapterPreview();
    $("chPreview").style.display = "block";
    toast("chapterization.json loaded — review and confirm", "info");
  } catch (err) {
    toast(`Invalid JSON: ${err.message}`, "error");
  }
}

function renderChapterPreview() {
  const chapters = state.chapterPreview;
  if (!chapters?.length) return;
  const container = $("pvChapterList");
  container.innerHTML = "";
  for (const ch of chapters) {
    const subs = ch.subtopics?.length ?? 0;
    const sources = (ch.subtopics ?? []).reduce((n, s) => n + (s.source_ids?.length ?? 0), 0);
    const div = document.createElement("div");
    div.style.cssText = "padding:7px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;font-size:12px;";
    div.innerHTML = `
      <span style="font-family:'JetBrains Mono',monospace;color:#8aabff;margin-right:8px;">Ch.${esc(String(ch.number))}</span>
      <strong>${esc(ch.title)}</strong>
      <span style="color:var(--muted);margin-left:10px;">${subs} subtopics · ${sources} source entries</span>
    `;
    container.appendChild(div);
  }
  $("pvChapterLabel").textContent = `Preview — ${chapters.length} chapter${chapters.length !== 1 ? "s" : ""} detected`;
}

window.confirmChapterImport = async function() {
  if (!state.chapterPreview?.length) return;
  try {
    if (state.chapterPreview.length === 1) {
      const ch = state.chapterPreview[0];
      const chapterId = `ch${ch.number}`;
      await API.importChapter(chapterId, ch);
    } else {
      await API.importChapterBulk(state.chapterPreview);
    }
    toast("Chapters imported", "success");
    $("chPreview").style.display = "none";
    state.chapterPreview = null;
    await loadChapters();
  } catch (err) {
    toast(`Import failed: ${err.message}`, "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// ADD CHAPTER MANUALLY
// ─────────────────────────────────────────────────────────────────────────────

async function addChapterManually() {
  const num   = $("newChNum")?.value.trim();
  const title = $("newChTitle")?.value.trim();
  const goal  = $("newChGoal")?.value.trim();
  const arc   = $("newChArc")?.value.trim();

  if (!num || !title || !goal) { toast("Number, Title and Goal are required", "error"); return; }

  try {
    await _req("POST", "/thesis/chapters", {
      number: parseInt(num), title, goal,
      chapter_arc: arc || undefined,
    });
    toast(`Chapter ${num} added`, "success");
    $("addChapterForm").style.display = "none";
    ["newChNum","newChTitle","newChGoal","newChArc"].forEach(id => { const el=$(id); if(el) el.value=""; });
    await loadChapters();
  } catch (err) {
    toast(`Add failed: ${err.message}`, "error");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// NEW THESIS (frontend scoping)
// ─────────────────────────────────────────────────────────────────────────────

function onThesisSelect(val) {
  if (val === "__new__") {
    $("newThesisPanel").style.display = "block";
    // Reset select to first real value
    const sel = $("thesisSelect");
    const firstReal = [...sel.options].find(o => o.value && o.value !== "__new__");
    if (firstReal) sel.value = firstReal.value;
    return;
  }
  _setActiveThesis(val);
  toast("Switched thesis — reloading data…", "info");
  loadAll();
}

// ─────────────────────────────────────────────────────────────────────────────
// PILLS UPDATE
// ─────────────────────────────────────────────────────────────────────────────

function updateSynopsisPill() {
  const pill = $("synopsisPill");
  if (state.synopsis) {
    pill.textContent = "✓ Imported";
    pill.className = "pill pill-done";
    $("card01").classList.add("done");
  } else {
    pill.textContent = "Not imported";
    pill.className = "pill pill-idle";
    $("card01").classList.remove("done");
  }
}

function updateChaptersPill() {
  const pill = $("chaptersPill");
  const chCount = state.chapters.length;
  const subCount = state.chapters.reduce((n, c) => n + (c.subtopics?.length ?? 0), 0);
  const arcsMissing = state.chapters.filter(c => !c.chapter_arc).length;

  if (!chCount) {
    pill.textContent = "No chapters";
    pill.className = "pill pill-idle";
  } else if (arcsMissing > 0) {
    pill.textContent = `${chCount} ch · ${subCount} sub · ${arcsMissing} arc missing`;
    pill.className = "pill pill-warn";
  } else {
    pill.textContent = `${chCount} ch · ${subCount} sub · All arcs set`;
    pill.className = "pill pill-done";
  }

  // Update thesis-strip stat chips
  const arcOk = arcsMissing === 0 && chCount > 0;
  $("pillChapters").textContent  = `${chCount} chapter${chCount !== 1 ? "s" : ""}`;
  $("pillSubtopics").textContent = `${subCount} subtopic${subCount !== 1 ? "s" : ""}`;
  $("pillArcs").textContent = arcOk ? "All arcs set" : arcsMissing > 0 ? `${arcsMissing} arc${arcsMissing !== 1 ? "s" : ""} missing` : "—";
  $("pillArcs").className = arcOk ? "stat-chip ok" : (arcsMissing > 0 ? "stat-chip warn" : "stat-chip");
}

// ─────────────────────────────────────────────────────────────────────────────
// MISC HELPERS
// ─────────────────────────────────────────────────────────────────────────────

window._toggleEl = function(id) {
  const el = $(id); if (!el) return;
  el.style.display = el.style.display === "none" ? "block" : "none";
};

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

function init() {
  // Thesis selector
  $("thesisSelect").addEventListener("change", e => onThesisSelect(e.target.value));

  // Card accordions
  document.querySelectorAll(".card-header[data-card]").forEach(h => {
    h.addEventListener("click", () => toggleCard(h.dataset.card));
  });

  // Synopsis file input
  $("synFileInput").addEventListener("change", e => onSynopsisFile(Array.from(e.target.files)));
  const synDrop = $("synDropZone");
  synDrop.addEventListener("dragover",  e => { e.preventDefault(); synDrop.classList.add("drag-over"); });
  synDrop.addEventListener("dragleave", () => synDrop.classList.remove("drag-over"));
  synDrop.addEventListener("drop", e => { e.preventDefault(); synDrop.classList.remove("drag-over"); onSynopsisFile(Array.from(e.dataTransfer.files)); });

  // Chapter file input
  $("chFileInput").addEventListener("change", e => onChapterFile(Array.from(e.target.files)));
  const chDrop = $("chDropZone");
  chDrop.addEventListener("dragover",  e => { e.preventDefault(); chDrop.classList.add("drag-over"); });
  chDrop.addEventListener("dragleave", () => chDrop.classList.remove("drag-over"));
  chDrop.addEventListener("drop", e => { e.preventDefault(); chDrop.classList.remove("drag-over"); onChapterFile(Array.from(e.dataTransfer.files)); });

  // Add chapter form
  $("btnShowAddChapter").addEventListener("click", () => _toggleEl("addChapterForm"));
  $("btnCancelAddChapter").addEventListener("click", () => _toggleEl("addChapterForm"));
  $("btnAddChapter").addEventListener("click", addChapterManually);

  // New thesis panel cancel
  $("btnCancelNewThesis").addEventListener("click", () => {
    $("newThesisPanel").style.display = "none";
  });

  // Boot
  renderThesisSelector();
  loadAll();
}

document.addEventListener("DOMContentLoaded", init);
