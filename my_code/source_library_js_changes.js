// ── spo_frontend/static/js/source_library.js — 2 changes ─────────────────────

// CHANGE 1 — add thesis selector helpers + loader after the ACTIONS block
// FIND:
const actions = {
  async loadLibrary() {
    try {
      const data = await API.getLibraryView();
      state.groups = data.groups ?? [];
      renderLibrary();
    } catch (err) {
      toast(`Failed to load library: ${err.message}`, "error");
    }
  },
};

// REPLACE WITH:
const actions = {
  async loadLibrary() {
    try {
      const data = await API.getLibraryView();
      state.groups = data.groups ?? [];
      renderLibrary();
    } catch (err) {
      toast(`Failed to load library: ${err.message}`, "error");
    }
  },
};

// ── Thesis selector (reads from same localStorage as thesis_setup.js) ─────────

function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || "";
}

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem("spo_theses") || "[]"); } catch { return []; }
}

function loadLibThesisSelector() {
  const sel = $("libThesisSelect");
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

function onLibThesisChange(id) {
  localStorage.setItem("spo_active_thesis", id);
  actions.loadLibrary();
}


// CHANGE 2 — wire up thesis selector in init and call loadLibThesisSelector
// FIND:
  // ── Boot ──────────────────────────────────────────────────────────────────
  actions.loadLibrary();
  loadThesisFolders();

// REPLACE WITH:
  // ── Thesis selector ───────────────────────────────────────────────────────
  loadLibThesisSelector();
  const libSel = $("libThesisSelect");
  if (libSel) libSel.addEventListener("change", e => onLibThesisChange(e.target.value));

  // ── Boot ──────────────────────────────────────────────────────────────────
  actions.loadLibrary();
  loadThesisFolders();
