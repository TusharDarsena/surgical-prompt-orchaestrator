/**
 * source_library.js
 *
 * Layers:
 *   state  →  actions (async, mutate state)  →  render (pure DOM)
 *
 * Card 01 — Import source JSON (with folder target selector)
 * Card 02 — Drive Setup (scan local + register Drive links)
 * Card 03 — Source Library browser (groups → docs → inline edit + re-import JSON)
 */

import * as API from "./source_library_api.js";

// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  groups:      [],   // full library: [{group_id, title, author, year, sources:[...], ...}]
  thesisFolders: [], // drive scan result: [{name, pdfs[], import_status, drive_linked}]
  fileQueue:   [],   // [{file, status:"queued"|"importing"|"done"|"error", message}]
};

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function uid() {
  return Math.random().toString(36).slice(2, 9);
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
  const card = $(id);
  card.classList.toggle("active");
}

// ─────────────────────────────────────────────────────────────────────────────
// CARD 01 — IMPORT SOURCE JSON
// ─────────────────────────────────────────────────────────────────────────────

function renderFileQueue() {
  const container = $("fileQueue");
  container.innerHTML = "";
  if (!state.fileQueue.length) return;

  for (const item of state.fileQueue) {
    const row = document.createElement("div");
    row.className = `file-queue-row${item.status === "done" ? " state-done" : item.status === "error" ? " state-error" : ""}`;
    row.id = `fqr-${item.id}`;

    const name = document.createElement("span");
    name.className = "fq-name";
    name.textContent = item.file.name;

    const status = document.createElement("span");
    status.className = `fq-status ${item.status === "done" ? "done" : item.status === "error" ? "error" : "pending"}`;
    status.textContent = item.status === "done"
      ? `✓ ${item.message}`
      : item.status === "error"
      ? `✕ ${item.message}`
      : "Queued";

    row.appendChild(name);
    row.appendChild(status);

    if (item.status === "queued" || item.status === "error") {
      const remove = document.createElement("button");
      remove.className = "fq-remove";
      remove.title = "Remove";
      remove.textContent = "✕";
      remove.addEventListener("click", () => {
        state.fileQueue = state.fileQueue.filter(f => f.id !== item.id);
        renderFileQueue();
      });
      row.appendChild(remove);
    }

    container.appendChild(row);
  }
}

function onFileSelect(files) {
  for (const file of files) {
    if (!file.name.endsWith(".json")) {
      toast(`${file.name} — only .json files are accepted`, "error");
      continue;
    }
    // Avoid duplicates
    if (state.fileQueue.find(f => f.file.name === file.name)) continue;
    state.fileQueue.push({ id: uid(), file, status: "queued", message: "" });
  }
  renderFileQueue();
  // Update import-all button
  $("btnImportAll").disabled = !state.fileQueue.some(f => f.status === "queued");
}

async function importAllQueued() {
  const targetGroupId = $("importTargetFolder").value;
  const queued = state.fileQueue.filter(f => f.status === "queued");
  if (!queued.length) { toast("No files queued", "error"); return; }

  $("btnImportAll").disabled = true;
  $("btnImportAll").textContent = "Importing…";

  for (const item of queued) {
    item.status = "importing";
    renderFileQueue();

    try {
      const text = await item.file.text();
      const parsed = JSON.parse(text);

      // If a target group is selected, attach the group_id so the backend
      // knows to add sources into an existing group rather than creating new.
      if (targetGroupId) parsed._target_group_id = targetGroupId;

      const result = await API.importSourceJson(parsed);
      item.status = "done";
      item.message = `Imported — ${result.sources_created ?? 0} sources created`;
    } catch (err) {
      item.status = "error";
      item.message = err.message;
    }

    renderFileQueue();
  }

  $("btnImportAll").disabled = false;
  $("btnImportAll").textContent = "💾 Import All Queued";

  // Reload library
  await actions.loadLibrary();
  toast("Import complete", "success");
}

// ─────────────────────────────────────────────────────────────────────────────
// CARD 02 — DRIVE SETUP
// ─────────────────────────────────────────────────────────────────────────────

async function handleScan() {
  const path = $("scanPath").value.trim();
  if (!path) { toast("Enter a folder path first", "error"); return; }
  const btn = $("btnScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const result = await API.scanLocalFolder(path);
    toast(`Scan complete — ${result.total_thesis_folders ?? 0} folders found`, "success");
    await loadThesisFolders();
  } catch (err) {
    toast(`Scan failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false; btn.textContent = "🔍 Scan Folder";
  }
}

async function handleRegisterLinks() {
  const folderId = $("driveFolderId").value.trim();
  if (!folderId) { toast("Paste a Drive folder ID first", "error"); return; }
  const btn = $("btnRegisterLinks");
  btn.disabled = true; btn.textContent = "Registering…";
  try {
    const result = await API.registerDriveLinks(folderId);
    toast(`Links registered — ${result.linked ?? 0} folders linked`, "success");
    await loadThesisFolders();
  } catch (err) {
    toast(`Register failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false; btn.textContent = "🔗 Register Drive Links";
  }
}

async function loadThesisFolders() {
  try {
    const data = await API.getLocalFiles();
    state.thesisFolders = data.folders ?? [];
    renderThesisFolders();
  } catch (_) {
    // Drive not scanned yet — leave list empty
  }
}

function renderThesisFolders() {
  const list = $("thesisList");
  list.innerHTML = "";

  if (!state.thesisFolders.length) {
    list.innerHTML = `<div style="font-size:12px;color:var(--muted);padding:12px 0;">No folders scanned yet. Enter the path above and click Scan Folder.</div>`;
    return;
  }

  for (const folder of state.thesisFolders) {
    const imported = folder.import_status?.imported;
    const importFailed = folder.import_status && !imported && folder.import_status.error;
    const linked = folder.drive_linked;

    const cls = imported ? "state-imported" : importFailed ? "state-error" : "";
    const tid = `thesis-${folder.name.replace(/\W/g, "_")}`;

    const row = document.createElement("div");
    row.className = `thesis-row ${cls}`;
    row.id = tid;

    row.innerHTML = `
      <div class="thesis-header" onclick="document.getElementById('${tid}').classList.toggle('open')">
        <span class="thesis-name">${esc(folder.name)}</span>
        <div class="thesis-badges">
          <span>${folder.pdfs?.length ?? 0} PDFs</span>
          ${imported
            ? `<span class="badge badge-ok">✓ Imported</span>`
            : importFailed
            ? `<span class="badge badge-error">❌ Import failed</span>`
            : `<span class="badge badge-idle">⬜ Not imported</span>`}
          ${linked
            ? `<span class="badge badge-linked">🔗 Linked</span>`
            : `<span class="badge badge-idle">☁ Not linked</span>`}
        </div>
        <span class="thesis-chevron">▾</span>
      </div>
      <div class="thesis-body">
        ${importFailed ? `<div class="error-inline">Import error: ${esc(folder.import_status.error)}</div>` : ""}
        <div class="pdf-grid">
          ${(folder.pdfs ?? []).map(pdf => pdf.drive_link
            ? `<div class="pdf-chip"><a href="${esc(pdf.drive_link)}" target="_blank">${esc(pdf.file_name)}</a></div>`
            : `<div class="pdf-chip no-link">${esc(pdf.file_name ?? pdf)}</div>`
          ).join("")}
        </div>
        <div class="copy-links-row">
          <button class="btn btn-ghost" style="padding:4px 12px;font-size:11px;"
            onclick="copyFolderLinks('${esc(folder.name)}')">
            📋 ${linked ? "Copy All Drive Links" : "Copy Filenames"}
          </button>
          <span class="copy-links-note">${linked ? "Paste into NotebookLM Add Source" : "No Drive links — upload manually to NotebookLM"}</span>
        </div>
      </div>
    `;

    list.appendChild(row);
  }
}

window.copyFolderLinks = async function(thesisName) {
  const folder = state.thesisFolders.find(f => f.name === thesisName);
  if (!folder) return;
  const linked = (folder.pdfs ?? []).filter(p => p.drive_link).map(p => p.drive_link);
  const filenames = (folder.pdfs ?? []).map(p => p.file_name ?? p);
  const text = linked.length ? linked.join("\n") : filenames.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast(linked.length ? "Drive links copied" : "Filenames copied", "success");
  } catch (_) {
    toast("Copy failed — select manually", "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// CARD 03 — SOURCE LIBRARY
// ─────────────────────────────────────────────────────────────────────────────

function renderLibrary() {
  const list = $("groupList");
  list.innerHTML = "";

  if (!state.groups.length) {
    list.innerHTML = `<div class="lib-empty">No sources imported yet. Use Card 01 to import a source JSON.</div>`;
    _updateLibraryPill();
    return;
  }

  for (const group of state.groups) {
    list.appendChild(_buildGroupRow(group));
  }

  _updateLibraryPill();
  _updateImportFolderSelect();
}

function _updateLibraryPill() {
  const pill = $("libraryPill");
  const total = state.groups.length;
  const docs  = state.groups.reduce((n, g) => n + (g.sources?.length ?? 0), 0);
  const indexed = state.groups.reduce((n, g) =>
    n + (g.sources?.filter(s => s.has_index_card).length ?? 0), 0);
  pill.textContent = total ? `${total} works · ${docs} docs · ${indexed} indexed` : "Empty";
  pill.className = total ? "pill pill-active" : "pill pill-idle";
}

function _updateImportFolderSelect() {
  // Sync Card 01 target folder dropdown with current groups
  const sel = $("importTargetFolder");
  // Keep the first option (create new)
  while (sel.options.length > 1) sel.remove(1);
  for (const g of state.groups) {
    const opt = document.createElement("option");
    opt.value = g.group_id;
    opt.textContent = `${g.author} (${g.year ?? "?"}) — ${g.title}`;
    sel.appendChild(opt);
  }
}

function _buildGroupRow(group) {
  const gid = group.group_id;
  const sourceCount = group.sources?.length ?? 0;
  const readyCount  = group.sources?.filter(s => s.has_index_card).length ?? 0;
  const rowId = `group-${gid}`;
  const editId = `gedit-${gid}`;
  const addDocId = `adddoc-${gid}`;

  const row = document.createElement("div");
  row.className = "group-row";
  row.id = rowId;

  // Header
  const header = document.createElement("div");
  header.className = "group-header";
  header.onclick = () => row.classList.toggle("open");
  header.innerHTML = `
    <div class="group-title-block">
      <div class="group-title">${esc(group.author)} (${esc(group.year ?? "?")}) — ${esc(group.title)}</div>
      <div class="group-sub">${esc(group.source_type ?? "")}${group.institution_or_publisher ? " · " + esc(group.institution_or_publisher) : ""} · ${sourceCount} doc${sourceCount !== 1 ? "s" : ""} · ${readyCount} indexed</div>
    </div>
    <div class="group-actions">
      <button class="icon-btn" title="Edit" onclick="event.stopPropagation(); _toggleEl('${editId}')">✏</button>
      <button class="icon-btn danger" title="Delete" onclick="event.stopPropagation(); _confirmDeleteGroup('${gid}', '${rowId}')">🗑</button>
    </div>
    <span class="group-chevron">▾</span>
  `;

  // Body
  const body = document.createElement("div");
  body.className = "group-body";

  // Inline group edit
  const inlineEdit = document.createElement("div");
  inlineEdit.className = "inline-edit";
  inlineEdit.id = editId;
  inlineEdit.style.display = "none";
  inlineEdit.innerHTML = `
    <div class="inline-edit-label">Edit Work Metadata</div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Description <span class="opt">(optional)</span></label>
        <textarea id="gdesc-${gid}" style="min-height:52px;">${esc(group.description ?? "")}</textarea>
      </div>
      <div class="form-group" style="max-width:210px;">
        <label class="form-label">Institution / Publisher</label>
        <input type="text" id="ginst-${gid}" value="${esc(group.institution_or_publisher ?? "")}"/>
      </div>
    </div>
    <div class="inline-edit-actions">
      <button class="btn btn-primary" style="padding:6px 14px;"
        onclick="_saveGroupEdit('${gid}')">Save</button>
      <button class="btn btn-ghost" style="padding:6px 14px;"
        onclick="_toggleEl('${editId}')">Cancel</button>
    </div>
  `;
  body.appendChild(inlineEdit);

  // Doc list
  const docList = document.createElement("div");
  docList.className = "doc-list";
  docList.id = `docs-${gid}`;

  for (const src of (group.sources ?? [])) {
    docList.appendChild(_buildDocBlock(gid, src));
  }
  body.appendChild(docList);

  // Add document form
  const addDocForm = document.createElement("div");
  addDocForm.className = "add-doc-form";
  addDocForm.id = addDocId;
  addDocForm.style.display = "none";
  addDocForm.innerHTML = `
    <div class="add-doc-label">Add Document</div>
    <div class="add-doc-grid">
      <div class="form-group"><label class="form-label">Label ★</label><input type="text" id="adlbl-${gid}" placeholder="Sharma Ch.3"/></div>
      <div class="form-group"><label class="form-label">Full Title ★</label><input type="text" id="adtitle-${gid}" placeholder="Chapter 3: …"/></div>
      <div class="form-group"><label class="form-label">Pages</label><input type="text" id="adpages-${gid}" placeholder="90–130"/></div>
      <div class="form-group"><label class="form-label">File name</label><input type="text" id="adfile-${gid}" placeholder="sharma_ch3.pdf"/></div>
    </div>
    <div style="display:flex;gap:8px;">
      <button class="btn btn-primary" style="padding:6px 14px;"
        onclick="_addDocument('${gid}')">Add</button>
      <button class="btn btn-ghost" style="padding:6px 14px;"
        onclick="_toggleEl('${addDocId}')">Cancel</button>
    </div>
  `;
  body.appendChild(addDocForm);

  const addDocBtn = document.createElement("button");
  addDocBtn.className = "btn btn-ghost";
  addDocBtn.style.cssText = "padding:5px 12px;font-size:11.5px;margin-top:6px;";
  addDocBtn.textContent = "+ Add Document";
  addDocBtn.addEventListener("click", () => _toggleEl(addDocId));
  body.appendChild(addDocBtn);

  row.appendChild(header);
  row.appendChild(body);
  return row;
}

function _buildDocBlock(gid, src) {
  const sid = src.source_id;
  const hasCard = src.has_index_card;
  const editId     = `dedit-${sid}`;
  const reimportId = `reimport-${sid}`;

  const frag = document.createDocumentFragment();

  // ── Doc row ──
  const row = document.createElement("div");
  row.className = "doc-row";
  row.id = `docrow-${sid}`;
  row.innerHTML = `
    <span class="doc-badge ${hasCard ? "indexed" : "not-indexed"}">${hasCard ? "✓" : "·"}</span>
    <span class="doc-label">${esc(src.label ?? sid)}</span>
    <span class="doc-title" title="${esc(src.title ?? "")}">${esc(src.title ?? "")}</span>
    <span class="doc-pages">${esc(src.page_range ?? "")}</span>
    <div class="doc-actions">
      <button class="icon-btn" title="Edit metadata"
        onclick="_toggleEl('${editId}')">✏</button>
      <button class="icon-btn json-btn" title="Paste NotebookLM JSON to re-import"
        onclick="_toggleEl('${reimportId}')">JSON</button>
      <button class="icon-btn danger" title="Delete document"
        onclick="_confirmDeleteSource('${gid}', '${sid}', 'docrow-${sid}')">🗑</button>
    </div>
  `;
  frag.appendChild(row);

  // ── Inline doc edit ──
  const editRow = document.createElement("div");
  editRow.className = "doc-edit-row";
  editRow.id = editId;
  editRow.style.display = "none";
  editRow.innerHTML = `
    <div class="doc-edit-grid">
      <div class="form-group"><label class="form-label">Label</label><input type="text" id="elbl-${sid}" value="${esc(src.label ?? "")}"/></div>
      <div class="form-group"><label class="form-label">Title</label><input type="text" id="etitle-${sid}" value="${esc(src.title ?? "")}"/></div>
      <div class="form-group"><label class="form-label">Pages</label><input type="text" id="epages-${sid}" value="${esc(src.page_range ?? "")}"/></div>
      <div class="form-group"><label class="form-label">File name</label><input type="text" id="efile-${sid}" value="${esc(src.file_name ?? "")}"/></div>
    </div>
    <div class="doc-edit-actions">
      <button class="btn btn-primary" style="padding:5px 12px;font-size:11.5px;"
        onclick="_saveDocEdit('${gid}', '${sid}')">Save</button>
      <button class="btn btn-ghost" style="padding:5px 12px;font-size:11.5px;"
        onclick="_toggleEl('${editId}')">Cancel</button>
    </div>
  `;
  frag.appendChild(editRow);

  // ── Re-import JSON panel ──
  const reimportPanel = document.createElement("div");
  reimportPanel.className = "reimport-panel";
  reimportPanel.id = reimportId;
  reimportPanel.style.display = "none";
  reimportPanel.innerHTML = `
    <div class="reimport-label">Paste NotebookLM JSON to re-import</div>
    <div class="reimport-note">Paste updated source JSON below. This replaces the index card and metadata for this document. The work (folder) stays the same.</div>
    <textarea id="rjson-${sid}" style="min-height:120px;font-family:'JetBrains Mono',monospace;font-size:11.5px;"
      placeholder='{ "title": "Chapter 1…", "key_claims": ["…"], "themes": ["…"], … }'></textarea>
    <div class="reimport-actions">
      <button class="btn btn-primary" style="padding:6px 14px;"
        onclick="_reimportDocJson('${gid}', '${sid}')">💾 Re-import</button>
      <button class="btn btn-ghost" style="padding:6px 14px;"
        onclick="_toggleEl('${reimportId}')">Cancel</button>
    </div>
  `;
  frag.appendChild(reimportPanel);

  return frag;
}

// ─────────────────────────────────────────────────────────────────────────────
// GLOBAL HANDLERS (called from inline onclick — attached to window)
// ─────────────────────────────────────────────────────────────────────────────

window._toggleEl = function(id) {
  const el = $(id);
  if (!el) return;
  el.style.display = el.style.display === "none" ? "block" : "none";
};

window._saveGroupEdit = async function(gid) {
  const desc = $(`gdesc-${gid}`)?.value ?? "";
  const inst = $(`ginst-${gid}`)?.value ?? "";
  try {
    await API.updateGroup(gid, {
      description: desc || null,
      institution_or_publisher: inst || null,
    });
    toast("Work updated", "success");
    _toggleEl(`gedit-${gid}`);
    await actions.loadLibrary();
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
};

window._confirmDeleteGroup = function(gid, rowId) {
  if (!confirm("Delete this work and all its documents?")) return;
  API.deleteGroup(gid).then(() => {
    const el = $(rowId);
    if (el) el.remove();
    state.groups = state.groups.filter(g => g.group_id !== gid);
    _updateLibraryPill();
    _updateImportFolderSelect();
    toast("Work deleted", "success");
  }).catch(err => toast(`Delete failed: ${err.message}`, "error"));
};

window._saveDocEdit = async function(gid, sid) {
  try {
    await API.updateSource(gid, sid, {
      label:      $(`elbl-${sid}`)?.value || null,
      title:      $(`etitle-${sid}`)?.value || null,
      page_range: $(`epages-${sid}`)?.value || null,
      file_name:  $(`efile-${sid}`)?.value || null,
    });
    toast("Document updated", "success");
    _toggleEl(`dedit-${sid}`);
    await actions.loadLibrary();
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
};

window._confirmDeleteSource = function(gid, sid, rowId) {
  if (!confirm("Delete this document?")) return;
  API.deleteSource(gid, sid).then(async () => {
    // Remove the doc row + its edit/reimport siblings
    [`docrow-${sid}`, `dedit-${sid}`, `reimport-${sid}`].forEach(id => {
      const el = $(id); if (el) el.remove();
    });
    toast("Document deleted", "success");
    await actions.loadLibrary(); // refresh counts
  }).catch(err => toast(`Delete failed: ${err.message}`, "error"));
};

window._reimportDocJson = async function(gid, sid) {
  const raw = $(`rjson-${sid}`)?.value ?? "";
  if (!raw.trim()) { toast("Paste JSON first", "error"); return; }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (_) {
    toast("Invalid JSON — check syntax", "error");
    return;
  }
  // Tag it so the backend knows which existing source to update
  parsed._target_group_id  = gid;
  parsed._target_source_id = sid;
  try {
    await API.importSourceJson(parsed);
    toast("Re-import successful", "success");
    _toggleEl(`reimport-${sid}`);
    await actions.loadLibrary();
  } catch (err) {
    toast(`Re-import failed: ${err.message}`, "error");
  }
};

window._addDocument = async function(gid) {
  const label = $(`adlbl-${gid}`)?.value ?? "";
  const title = $(`adtitle-${gid}`)?.value ?? "";
  if (!label || !title) { toast("Label and Title are required", "error"); return; }
  try {
    await API.createSource(gid, {
      label,
      title,
      chapter_or_section: title,
      page_range: $(`adpages-${gid}`)?.value || null,
      file_name:  $(`adfile-${gid}`)?.value  || null,
    });
    toast(`Added: ${label}`, "success");
    _toggleEl(`adddoc-${gid}`);
    await actions.loadLibrary();
  } catch (err) {
    toast(`Add failed: ${err.message}`, "error");
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// REGISTER NEW WORK FORM
// ─────────────────────────────────────────────────────────────────────────────

async function registerNewWork() {
  const title  = $("newTitle").value.trim();
  const author = $("newAuthor").value.trim();
  const year   = $("newYear").value.trim();
  const type   = $("newType").value;
  const inst   = $("newInst").value.trim();
  const desc   = $("newDesc").value.trim();

  if (!title || !author) { toast("Title and Author are required", "error"); return; }

  try {
    await API.createGroup({ title, author, year: year ? parseInt(year) : null, source_type: type, institution_or_publisher: inst || null, description: desc || null });
    toast(`Registered: ${title}`, "success");
    $("addGroupForm").style.display = "none";
    // clear fields
    ["newTitle","newAuthor","newYear","newInst","newDesc"].forEach(id => { const el=$(id); if(el) el.value=""; });
    await actions.loadLibrary();
  } catch (err) {
    toast(`Register failed: ${err.message}`, "error");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ACTIONS
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

function init() {
  // ── Card 01: drag-drop + file select ──────────────────────────────────────
  const dropZone = $("dropZone");
  dropZone.addEventListener("dragover",  e => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    onFileSelect(Array.from(e.dataTransfer.files));
  });
  $("fileInput").addEventListener("change", e => onFileSelect(Array.from(e.target.files)));
  $("btnImportAll").addEventListener("click", importAllQueued);

  // ── Card 02: scan + drive ─────────────────────────────────────────────────
  $("btnScan").addEventListener("click", handleScan);
  $("btnRegisterLinks").addEventListener("click", handleRegisterLinks);

  // ── Card 03: register new work ────────────────────────────────────────────
  $("btnRegisterWork").addEventListener("click", registerNewWork);
  $("btnShowAddGroup").addEventListener("click", () => {
    $("addGroupForm").style.display = "block";
  });
  $("btnCancelAddGroup").addEventListener("click", () => {
    $("addGroupForm").style.display = "none";
  });

  // ── Card accordions ───────────────────────────────────────────────────────
  document.querySelectorAll(".card-header[data-card]").forEach(h => {
    h.addEventListener("click", () => toggleCard(h.dataset.card));
  });

  // ── Boot ──────────────────────────────────────────────────────────────────
  actions.loadLibrary();
  loadThesisFolders();
}

document.addEventListener("DOMContentLoaded", init);
