/**
 * thesis_setup.js
 *
 * Multi-thesis: each thesis has an isolated backend namespace.
 * The active thesis_id is appended as ?thesis_id=<id> on every API call.
 *
 * localStorage keys:
 *   spo_theses        — [{id, title, author}]
 *   spo_active_thesis — string id
 */

const BASE = window.SPO_API_BASE || "http://localhost:8000";

// ─────────────────────────────────────────────────────────────────────────────
// API — all calls include ?thesis_id=
// ─────────────────────────────────────────────────────────────────────────────

function _tid() {
  return _activeThesisId();
}

async function _req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function _p(path) {
  // Only append thesis_id when non-empty (empty = root namespace, no param needed)
  const id = _activeThesisId();
  if (!id) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}thesis_id=${encodeURIComponent(id)}`;
}

const API = {
  getSynopsis: () => _req("GET", _p("/thesis/synopsis")),
  putSynopsis: (d) => _req("PUT", _p("/thesis/synopsis"), d),
  patchSynopsis: (d) => _req("PATCH", _p("/thesis/synopsis"), d),
  deleteSynopsis: () => _req("DELETE", _p("/thesis/synopsis")),
  getChapters: () => _req("GET", _p("/thesis/chapters")),
  getChapter: (id) => _req("GET", _p(`/thesis/chapters/${id}`)),
  patchChapter: (id, d) => _req("PATCH", _p(`/thesis/chapters/${id}`), d),
  deleteChapter: (id) => _req("DELETE", _p(`/thesis/chapters/${id}`)),
  deleteSubtopic: (cid, sid) => _req("DELETE", _p(`/thesis/chapters/${cid}/subtopics/${sid}`)),
  importThesis: (d) => _req("POST", _p("/import/thesis"), d),
  importChapterBulk: (d) => _req("POST", _p("/import/chapterization/bulk"), d),
  importChapter: (id, d) => _req("POST", _p(`/import/chapterization/${id}`), d),
  listTheses: () => _req("GET", "/thesis/list"),
  deleteThesis: (id) => _req("DELETE", `/thesis/namespace/${encodeURIComponent(id)}`),
};

// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  synopsis: null,
  chapters: [],
  synopsisPreview: null,
  chapterPreview: null,
  synopsisLoaded: false,
};

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function toast(msg, type = "info", duration = 3500) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  $("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), duration);
}

function toggleCard(id) {
  $(id).classList.toggle("active");
}

// ─────────────────────────────────────────────────────────────────────────────
// THESIS SELECTOR — localStorage index
// ─────────────────────────────────────────────────────────────────────────────

const THESES_KEY = "spo_theses";

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem(THESES_KEY) || "[]"); } catch { return []; }
}

function _saveThesesIndex(list) {
  localStorage.setItem(THESES_KEY, JSON.stringify(list));
}

function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || "";
}

function _setActiveThesis(id) {
  localStorage.setItem("spo_active_thesis", id);
}

function _upsertThesisIndex(synopsis) {
  // Always use whatever the current active thesis id is — never change it here.
  const id = _activeThesisId();
  const theses = _loadThesesIndex();
  const existing = theses.findIndex(t => t.id === id);
  const entry = {
    id,
    title: synopsis.title || "Untitled",
    author: synopsis.researcher || synopsis.author || "",
  };
  if (existing >= 0) theses[existing] = entry;
  else theses.push(entry);
  _saveThesesIndex(theses);
  // NOTE: intentionally no _setActiveThesis call here
}

function _removeThesisFromIndex(id) {
  const theses = _loadThesesIndex().filter(t => t.id !== id);
  _saveThesesIndex(theses);
  if (_activeThesisId() === id) {
    _setActiveThesis(theses.length ? theses[0].id : "");
  }
}

function renderThesisSelector() {
  const sel = $("thesisSelect");
  const theses = _loadThesesIndex();
  const activeId = _activeThesisId();

  sel.innerHTML = "";

  if (!theses.length) {
    sel.innerHTML = `<option value="">— No theses yet —</option>`;
  } else {
    for (const t of theses) {
      const opt = document.createElement("option");
      opt.value = t.id;
      let titleDisplay = t.title;
      if (titleDisplay.length > 55) titleDisplay = titleDisplay.substring(0, 55) + '…';
      opt.textContent = titleDisplay;
      if (t.id === activeId) opt.selected = true;
      sel.appendChild(opt);
    }
  }

  // "+ Import new thesis" option
  const newOpt = document.createElement("option");
  newOpt.value = "__new__";
  newOpt.textContent = "+ Import new thesis…";
  sel.appendChild(newOpt);

  // Only show delete button for namespaced theses (not root "")
  const delBtn = $("btnDeleteThesis");
  if (delBtn) {
    delBtn.style.display = activeId ? "inline-flex" : "none";
  }


}

// ─────────────────────────────────────────────────────────────────────────────
// LOAD DATA
// ─────────────────────────────────────────────────────────────────────────────

async function loadAll() {
  // Load thesis list first so the selector is correct before data loads
  await loadThesesList();
  await Promise.allSettled([loadSynopsis(), loadChapters()]);
}

async function loadThesesList() {
  try {
    const list = await API.listTheses();
    // [{thesis_id, title, author}] — backend is source of truth
    const mapped = list.map(t => ({
      id: t.thesis_id,
      title: t.title || "Untitled",
      author: t.author || "",
    }));
    _saveThesesIndex(mapped);
    // Do not aggressively reset active thesis if missing from backend list.
    // We trust localStorage so the user can stay in their draft workspace.
    // const activeId = _activeThesisId();
    // if (activeId && !mapped.find(t => t.id === activeId)) {
    //   _setActiveThesis("");
    // }
  } catch (_) {
    // Backend unavailable — keep whatever localStorage has
  }
  renderThesisSelector();
}

async function loadSynopsis() {
  try {
    state.synopsis = await API.getSynopsis();
    state.synopsisLoaded = true;
    // Register this thesis in the index under its current active id
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
// THESIS SELECTOR ACTIONS
// ─────────────────────────────────────────────────────────────────────────────

function onThesisSelect(val) {
  if (val === "__new__") {
    // Reset select back, then directly open file picker
    const sel = $("thesisSelect");
    const firstReal = [...sel.options].find(o => o.value && o.value !== "__new__");
    if (firstReal) sel.value = firstReal.value;
    // Directly trigger hidden file input — no intermediate browse section
    $("newThesisFileInput").click();
    return;
  }
  _setActiveThesis(val);
  renderThesisSelector();
  toast("Switched thesis — reloading…", "info");
  loadAll();
}

async function deleteActiveThesis() {
  const id = _activeThesisId();
  if (!id) return; // empty = root thesis, cannot delete
  const theses = _loadThesesIndex();
  const thesis = theses.find(t => t.id === id);
  const label = thesis ? thesis.title : id;
  if (!confirm(`Delete "${label}" and all its data permanently?`)) return;
  try {
    await API.deleteThesis(id);
    _removeThesisFromIndex(id);
    renderThesisSelector();
    toast("Thesis deleted", "success");
    loadAll();
  } catch (err) {
    toast(`Delete failed: ${err.message}`, "error");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// NEW THESIS — file picked directly, no drop zone panel
// ─────────────────────────────────────────────────────────────────────────────

async function onNewThesisFile(files) {
  if (!files.length) return;
  const file = files[0];
  // Reset input so the same file can be picked again later
  $("newThesisFileInput").value = "";
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    // Register a fresh id for this thesis
    const newId = `t_${Date.now()}`;
    parsed._frontend_id = newId;
    _setActiveThesis(newId);
    await API.importThesis(parsed);   // POST /import/thesis?thesis_id=<newId>
    _upsertThesisIndex(parsed);
    renderThesisSelector();
    toast("New thesis imported and activated", "success");
    loadAll();
  } catch (err) {
    toast(`Import failed: ${err.message}`, "error");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// SYNOPSIS RENDER + INLINE EDIT
// ─────────────────────────────────────────────────────────────────────────────

function renderSynopsis() {
  const block = $("synopsisBlock");
  const syn = state.synopsis;

  const dropZone = $("synDropZone");
  const dropZoneLabel = $("synDropZoneLabel");

  if (!syn) {
    block.style.display = "none";
    if (dropZone) dropZone.style.display = "flex";
    if (dropZoneLabel) dropZoneLabel.style.display = "block";
    const card02 = $("card02");
    if (card02) card02.style.display = "none";
    return;
  }

  // If we have synopsis
  block.style.display = "block";
  if (dropZone) dropZone.style.display = "none";
  if (dropZoneLabel) dropZoneLabel.style.display = "none";
  const card02 = $("card02");
  if (card02) card02.style.display = "block";

  const title = syn.title || "";
  const author = syn.researcher || syn.author || "";
  const field = syn.field || "";
  const scope = syn.temporal_scope || syn.scope_and_limits || "";
  
  const frameworksArray = Array.isArray(syn.methodology?.theoretical_frameworks)
    ? syn.methodology.theoretical_frameworks
    : (syn.theoretical_frameworks ? (typeof syn.theoretical_frameworks === "string" ? syn.theoretical_frameworks.split(",") : syn.theoretical_frameworks) : []);

  const frameworksHtml = frameworksArray.filter(Boolean).map(f => {
    const clean = String(f).trim().replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    return `<span class="theme-chip framework-chip">${esc(clean)}</span>`;
  }).join("");

  let themesArray = [];
  if (Array.isArray(syn.central_themes)) {
    themesArray = syn.central_themes;
  } else if (syn.themes) {
    themesArray = typeof syn.themes === "string" ? syn.themes.split(",").map(s => s.trim()) : syn.themes;
  }
  
  const themesHtml = themesArray.filter(Boolean).map(t => {
    const clean = String(t).trim().replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    return `<span class="theme-chip">${esc(clean)}</span>`;
  }).join("");

  const rawThemes = themesArray.join(", ");
  const rawFrameworks = frameworksArray.join(", ");
  const argument = syn.core_argument || syn.central_argument || "";

  block.innerHTML = `
    <!-- VIEW MODE -->
    <div class="syn-view-mode">
      <div class="syn-editorial-header">
        <h1 class="syn-title-hero">${esc(title) || "Untitled Thesis"}</h1>
        <div class="syn-subtitle">
          By <strong>${esc(author) || "Unknown Author"}</strong>
          ${scope ? `<span class="bullet-sep">•</span> ${esc(scope)}` : ""}
          ${field ? `<span class="bullet-sep">•</span> <span class="syn-field-tag">${esc(field)}</span>` : ""}
        </div>
        <div class="synopsis-block-actions hero-actions">
          <button class="btn btn-ghost" onclick="document.getElementById('synFileInput').click()" title="Re-import JSON">↻ Re-import</button>
        </div>
      </div>

      <div class="syn-tag-cloud">
        ${frameworksHtml ? `<div class="syn-tag-group"><span class="syn-tag-label">FRAMEWORKS</span> <div class="syn-tags">${frameworksHtml}</div></div>` : ""}
        ${themesHtml ? `<div class="syn-tag-group"><span class="syn-tag-label">THEMES</span> <div class="syn-tags">${themesHtml}</div></div>` : ""}
      </div>

      <div class="syn-argument-section">
        <span class="syn-tag-label" style="display:block; margin-bottom:8px;">ARGUMENT</span>
        <blockquote class="syn-argument-quote">
          ${esc(argument)}
        </blockquote>
      </div>
    </div>
  `;
}

window.deleteSynopsis = async function () {
  if (!confirm("Delete the synopsis for this thesis? This cannot be undone.")) return;
  try {
    await API.deleteSynopsis();
    state.synopsis = null;
    renderSynopsis();
    updateSynopsisPill();
    await loadThesesList(); // refresh selector — thesis may disappear if no data left
    toast("Synopsis deleted", "success");
  } catch (err) {
    toast(`Delete failed: ${err.message}`, "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// SYNOPSIS IMPORT (existing drop zone in Card 01 — updates active thesis)
// ─────────────────────────────────────────────────────────────────────────────

async function onSynopsisFile(files) {
  if (!files.length) return;
  try {
    const text = await files[0].text();
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
  $("pvSynTitle").textContent = p.title || "—";
  $("pvSynAuthor").textContent = p.researcher || p.author || "—";
  $("pvSynField").textContent = p.field || "—";
  $("pvSynScope").textContent = p.temporal_scope || "—";
  $("pvSynArg").textContent = p.core_argument || p.central_argument || "—";
}

window.confirmSynImport = async function () {
  if (!state.synopsisPreview) return;
  try {
    await API.importThesis(state.synopsisPreview);
    toast("Synopsis imported", "success");
    $("synPreview").style.display = "none";
    state.synopsisPreview = null;
    await loadSynopsis();
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
  const dropZone = $("chDropZone");
  const dropZoneLabel = $("chDropZoneLabel");
  const reimportBtn = $("chReimportBtn");

  list.innerHTML = "";
  if (!state.chapters.length) {
    if (dropZone) dropZone.style.display = "flex";
    if (dropZoneLabel) dropZoneLabel.style.display = "block";
    if (reimportBtn) reimportBtn.style.display = "none";
    list.innerHTML = `<div class="chapters-empty">No chapters yet. Import chapterization.json above.</div>`;
    updateChaptersPill();
    return;
  }
  
  if (dropZone) dropZone.style.display = "none";
  if (dropZoneLabel) dropZoneLabel.style.display = "none";
  if (reimportBtn) reimportBtn.style.display = "inline-flex";

  for (const ch of state.chapters) {
    list.appendChild(_buildChapterRow(ch));
  }
  updateChaptersPill();
}

function _buildChapterRow(ch) {
  const cid = ch.chapter_id;
  const subtopics = ch.subtopics || [];
  const hasArc = Boolean(ch.chapter_arc);

  const row = document.createElement("div");
  row.id = `ch-${cid}`;
  row.className = `chapter-row${hasArc ? "" : " arc-missing"}`;

  const subsHtml = subtopics.map(sub => `
    <div class="subtopic-row" id="sub-${cid}-${sub.subtopic_id}">
      <span class="sub-num">${esc(sub.number)}</span>
      <span class="sub-title">${esc(sub.title)}</span>
      <span class="sub-goal">${esc(sub.goal)}</span>
    </div>
  `).join("");

  row.innerHTML = `
    <div class="chapter-header" onclick="toggleChapterAccordion('${esc(cid)}')">
      <span class="ch-num">Ch.${esc(String(ch.number))}</span>
      <span class="ch-title ch-val">${esc(ch.title)}</span>
      <span class="arc-badge ${hasArc ? "ok" : "warn"}">${hasArc ? "Arc ✓" : "⚠ Arc missing"}</span>
      <div class="chapter-actions">
        <span class="chapter-chevron">▾</span>
      </div>
    </div>
    <div class="chapter-body">
      <div class="ch-goal-row">
        <span class="ch-goal ch-val">${esc(ch.goal)}</span>
      </div>
      <div class="subtopic-list">
        <span class="sub-list-label">SUBTOPICS</span>
        ${subsHtml}
      </div>
    </div>
  `;
  return row;
}

window.toggleChapterAccordion = function (cid) {
  const row = document.getElementById(`ch-${cid}`);
  if (!row) return;
  // If we are editing, do not toggle accordion
  if (row.classList.contains("editing")) return;
  
  const isOpening = !row.classList.contains("open");
  
  // Close all other open chapters
  if (isOpening) {
    document.querySelectorAll(".chapter-row.open").forEach(r => {
      r.classList.remove("open");
    });
    row.classList.add("open");
  } else {
    row.classList.remove("open");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// CHAPTER FILE IMPORT
// ─────────────────────────────────────────────────────────────────────────────

async function onChapterFile(files) {
  if (!files.length) return;
  try {
    let all = [];
    for (const file of files) {
      const text = await file.text();
      const parsed = JSON.parse(text);
      all = all.concat(Array.isArray(parsed) ? parsed : [parsed]);
    }
    state.chapterPreview = all;
    renderChapterPreview();
    $("chPreview").style.display = "block";
    toast(`${files.length > 1 ? files.length + " files" : "File"} loaded — review and confirm`, "info");
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
  $("pvChapterLabel").textContent =
    `Preview — ${chapters.length} chapter${chapters.length !== 1 ? "s" : ""} detected`;
}

window.confirmChapterImport = async function () {
  if (!state.chapterPreview?.length) return;
  try {
    if (state.chapterPreview.length === 1) {
      const ch = state.chapterPreview[0];
      await API.importChapter(`ch${ch.number}`, ch);
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
// PILLS
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

  const arcOk = arcsMissing === 0 && chCount > 0;
  $("pillChapters").textContent = `${chCount} chapter${chCount !== 1 ? "s" : ""}`;
  $("pillSubtopics").textContent = `${subCount} subtopic${subCount !== 1 ? "s" : ""}`;
  $("pillArcs").textContent = arcOk
    ? "All arcs set"
    : arcsMissing > 0 ? `${arcsMissing} arc${arcsMissing !== 1 ? "s" : ""} missing` : "—";
  $("pillArcs").className = arcOk ? "stat-chip ok"
    : arcsMissing > 0 ? "stat-chip warn" : "stat-chip";
}

// ─────────────────────────────────────────────────────────────────────────────
// MISC
// ─────────────────────────────────────────────────────────────────────────────

window._toggleEl = function (id) {
  const el = $(id); if (!el) return;
  el.style.display = el.style.display === "none" ? "block" : "none";
};

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

function init() {
  $("thesisSelect").addEventListener("change", e => onThesisSelect(e.target.value));
  $("btnDeleteThesis").addEventListener("click", deleteActiveThesis);

  document.querySelectorAll(".card-header[data-card]").forEach(h => {
    h.addEventListener("click", () => toggleCard(h.dataset.card));
  });

  $("newThesisFileInput").addEventListener("change", e => {
    onNewThesisFile(Array.from(e.target.files));
  });

  $("synFileInput").addEventListener("change", e => onSynopsisFile(Array.from(e.target.files)));
  const synDrop = $("synDropZone");
  synDrop.addEventListener("dragover", e => { e.preventDefault(); synDrop.classList.add("drag-over"); });
  synDrop.addEventListener("dragleave", () => synDrop.classList.remove("drag-over"));
  synDrop.addEventListener("drop", e => {
    e.preventDefault(); synDrop.classList.remove("drag-over");
    onSynopsisFile(Array.from(e.dataTransfer.files));
  });

  $("chFileInput").addEventListener("change", e => onChapterFile(Array.from(e.target.files)));
  const chDrop = $("chDropZone");
  chDrop.addEventListener("dragover", e => { e.preventDefault(); chDrop.classList.add("drag-over"); });
  chDrop.addEventListener("dragleave", () => chDrop.classList.remove("drag-over"));
  chDrop.addEventListener("drop", e => {
    e.preventDefault(); chDrop.classList.remove("drag-over");
    onChapterFile(Array.from(e.dataTransfer.files));
  });

  renderThesisSelector();
  loadAll();
}

document.addEventListener("DOMContentLoaded", init);