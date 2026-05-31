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
  groups:        [],   // full library: [{group_id, title, author, year, sources:[...], ...}]
  thesisFolders: [], // drive scan result: [{thesis_name, files[], pdfs[], imported, imported_at, import_group_id, import_error, drive_links_registered, drive_links}]
  fileQueue:     [],   // [{file, status:"queued"|"importing"|"done"|"error", message}]
  pdfSelections: {},   // { thesis_name → Set<string> } of filenames user wants to include
  globalCardOutputDir: "",
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

// ── NotebookLM link helpers ────────────────────────────────────────────────────
// Single source of truth for resolving and building notebook links.
// Prefers the live indexState (most up-to-date) then falls back to the scan
// entry field returned by /drive/local-files.

function _getNotebookId(folder) {
  const s = (typeof indexState !== "undefined" ? indexState.statuses[folder.thesis_name] : null) || {};
  return s.index_notebook_id || folder.index_notebook_id || null;
}

function _buildNotebookLink(notebookId, displayText) {
  const a = document.createElement("a");
  a.className = "nlm-notebook-link";
  a.href = `https://notebooklm.google.com/notebook/${encodeURIComponent(notebookId)}`;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.title = "Open in NotebookLM ↗";
  a.textContent = displayText;
  return a;
}

// ── PDF selection helpers ──────────────────────────────────────────────────────

const PDF_SEL_KEY = n => `spo_pdf_sel_${n.replace(/\W/g, "_")}`;

function _initPdfSelection(thesisName, allFiles) {
  if (state.pdfSelections[thesisName]) return; // already initialised
  const stored = localStorage.getItem(PDF_SEL_KEY(thesisName));
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      // Intersect stored selection with current files (files may have been added/removed)
      state.pdfSelections[thesisName] = new Set(parsed.filter(f => allFiles.includes(f)));
      // Add any newly-scanned files that weren't in previous selection → include by default
      for (const f of allFiles) {
        if (!parsed.includes(f)) state.pdfSelections[thesisName].add(f);
      }
      return;
    } catch { /* fall through to default */ }
  }
  state.pdfSelections[thesisName] = new Set(allFiles);
}

function _savePdfSelection(thesisName) {
  const sel = state.pdfSelections[thesisName];
  if (!sel) return;
  localStorage.setItem(PDF_SEL_KEY(thesisName), JSON.stringify([...sel]));
}

function _getPdfSelection(thesisName) {
  return state.pdfSelections[thesisName] ?? new Set();
}

function _getAlreadyUploaded(thesisName) {
  // indexState is defined later in the file but in the same module scope
  const s = (typeof indexState !== "undefined" ? indexState.statuses[thesisName] : null) || {};
  return new Set(s.sources_uploaded ?? []);
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

  // Resolve the active thesis title — used to scope the scan to one Level 2 folder.
  // Without this, the cleanup step would consider ALL entries under the root as candidates
  // for deletion, which would wipe Drive links for theses you're not working on.
  const activeId = _activeThesisId();
  if (!activeId) { toast("Select an active thesis first", "error"); return; }
  const theses = _loadThesesIndex();
  const activeThesis = theses.find(t => t.id === activeId);
  if (!activeThesis?.title) { toast("Active thesis has no title — reload the page", "error"); return; }
  const thesisFolderName = activeThesis.title;

  const btn = $("btnScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const result = await API.scanLocalFolder(path, thesisFolderName);
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

    // Filter to the active thesis only — the scan file is global by design
    // (it supports bulk discovery across all thesis folders at once), but the
    // UI must show only the folder that belongs to the currently-active thesis.
    const activeId = _activeThesisId();
    const theses = _loadThesesIndex();
    const activeThesis = theses.find(t => t.id === activeId);
    const activeTitle = activeThesis?.title;

    let folders = data.thesis_folders ?? [];
    if (activeTitle) {
      folders = folders.filter(f => {
        // In the backend, f.thesis_name is the immediate parent folder of the PDFs (the source group).
        // If PDFs are inside a subfolder (e.g., .../new/SourceGroupA/), parts[-2] is "new" (the active thesis).
        // If PDFs are directly inside the active thesis folder, parts[-1] is "new".
        const p = f.folder_path || f.level2_path || "";
        const parts = p.replace(/\\/g, '/').split('/').filter(Boolean);
        if (parts.length >= 1 && parts[parts.length - 1] === activeTitle) return true;
        if (parts.length >= 2 && parts[parts.length - 2] === activeTitle) return true;
        return false;
      });
    }

    state.thesisFolders = folders.map(folder => {
        // Hydrate pdfs array for UI rendering
        folder.pdfs = (folder.files ?? []).map(fileName => ({
            file_name: fileName,
            drive_link: folder.drive_links?.[fileName] || null
        }));
        // Init PDF selection (all checked by default, localStorage overrides)
        _initPdfSelection(folder.thesis_name, folder.files ?? []);
        return folder;
    });
    renderThesisFolders();
  } catch (_) {
    // Drive not scanned yet — leave list empty
  }
}

function renderThesisFolders() {
  renderUnifiedTable();
}

// ── renderUnifiedTable: single master render for all thesis rows ───────────────
// Replaces renderThesisFolders() + renderIndexTable().
// Each thesis gets one accordion row:
//   Summary: [chevron] [title] [PDF count] [drive badge] [status chip] [run btn]
//   Tray:    [3-col PDF checkbox grid] [file-status panel] [copy button]

function renderUnifiedTable() {
  const body = $("unifiedTableBody");
  if (!body) return;
  body.innerHTML = "";

  if (!state.thesisFolders.length) {
    body.innerHTML = `<div class="index-loading">Scan a folder in Drive Setup first.</div>`;
    _updateIndexPill();
    return;
  }

  for (const folder of state.thesisFolders) {
    body.appendChild(_buildUnifiedRow(folder));
  }

  _updateIndexPill();
  _startPoller();
}

function _buildUnifiedRow(folder) {
  const thesisName = folder.thesis_name;
  const rowId = `uf-${thesisName.replace(/\W/g, "_")}`;
  const trayId = `${rowId}-tray`;

  const s = (typeof indexState !== "undefined" ? indexState.statuses[thesisName] : null) || {};
  const status   = s.status || "idle";
  const imported = s.status === "done" || s.status === "warn" || folder.imported;
  const hasDrive = folder.drive_links_registered;
  const pdfCount = folder.pdfs?.length ?? 0;
  const groupId  = s.group_id || folder.import_group_id;
  const notebookId = _getNotebookId(folder);

  // ── Row wrapper ──
  const row = document.createElement("div");
  row.className = `unified-row state-${status}`;
  row.id = rowId;

  // ── Summary strip ──
  const summary = document.createElement("div");
  summary.className = "unified-row-summary";

  // Chevron
  const chevron = document.createElement("span");
  chevron.className = "unified-chevron";
  chevron.textContent = "►";
  summary.appendChild(chevron);

  // Title (with optional notebook link)
  const titleEl = document.createElement("span");
  titleEl.className = "unified-title";
  titleEl.title = thesisName; // full title on hover
  if (notebookId) {
    const link = _buildNotebookLink(notebookId, thesisName + " ↗");
    titleEl.appendChild(link);
  } else {
    titleEl.textContent = thesisName;
  }
  summary.appendChild(titleEl);

  // PDF count
  const countEl = document.createElement("span");
  countEl.className = "unified-pdf-count";
  countEl.textContent = pdfCount;
  summary.appendChild(countEl);

  // Drive badge
  const driveCell = document.createElement("span");
  driveCell.className = "unified-drive-cell";
  const driveBadge = document.createElement("span");
  if (hasDrive) {
    driveBadge.className = "badge-drive";
    driveBadge.textContent = "🟢 Drive";
  } else {
    driveBadge.className = "badge-local";
    driveBadge.title = "Drive links not registered — upload will use local paths";
    driveBadge.textContent = "🟡 Local";
  }
  driveCell.appendChild(driveBadge);
  summary.appendChild(driveCell);

  // Status chip
  const statusCell = document.createElement("div");
  statusCell.className = "unified-status-cell";
  const chip = document.createElement("span");
  chip.className = `index-status-chip ${_chipClass(status, imported)}`;
  chip.textContent = _chipLabel(status, imported);
  statusCell.appendChild(chip);
  // Progress note under chip for running/error/warn states
  if (status === "running") {
    const uploaded = s.sources_uploaded?.length ?? 0;
    const total    = (s.sources_uploaded?.length ?? 0) + (s.sources_failed?.length ?? 0);
    const note = document.createElement("span");
    note.className = "unified-status-note";
    note.textContent = uploaded > 0 || total > 0 ? `${uploaded}/${Math.max(uploaded, total)} files` : "Starting…";
    statusCell.appendChild(note);
  } else if (status === "error" && s.error) {
    const note = document.createElement("span");
    note.className = "unified-status-note note-error";
    note.textContent = s.error.slice(0, 80);
    statusCell.appendChild(note);
  } else if (status === "warn" && s.warn_message) {
    const note = document.createElement("span");
    note.className = "unified-status-note note-warn";
    note.textContent = s.warn_message.slice(0, 80);
    statusCell.appendChild(note);
  }
  summary.appendChild(statusCell);

  // Action buttons
  const actionCell = document.createElement("div");
  actionCell.className = "unified-action-cell";

  if (status === "running") {
    const stopBtn = document.createElement("button");
    stopBtn.className = "btn btn-danger";
    stopBtn.style.cssText = "padding:4px 10px;font-size:11px;";
    stopBtn.textContent = "Stop";
    stopBtn.addEventListener("click", (e) => { e.stopPropagation(); handleStop(thesisName); });
    actionCell.appendChild(stopBtn);
  } else {
    const isRerun = imported || status === "done" || status === "warn";
    const runBtn = document.createElement("button");
    runBtn.className = "btn btn-run";
    runBtn.textContent = isRerun ? "Re-run" : "▶ Run";
    runBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (isRerun && groupId) showRerunWarning(thesisName, groupId);
      else handleRunSingle(thesisName);
    });
    actionCell.appendChild(runBtn);

    if (isRerun && groupId) {
      const openBtn = document.createElement("button");
      openBtn.className = "idx-open-btn";
      openBtn.title = "Go to group in Source Library →";
      openBtn.textContent = "↗";
      openBtn.addEventListener("click", (e) => { e.stopPropagation(); scrollToGroup(groupId); });
      actionCell.appendChild(openBtn);
    }
  }
  summary.appendChild(actionCell);

  // ── Accordion toggle — auto-collapse siblings ──
  summary.addEventListener("click", (e) => {
    if (e.target.tagName === "A" || e.target.tagName === "BUTTON") return;
    const isOpen = row.classList.contains("open");
    // Collapse all other rows
    $("unifiedTableBody").querySelectorAll(".unified-row.open").forEach(r => r.classList.remove("open"));
    if (!isOpen) {
      row.classList.add("open");
      _renderPdfCheckboxGrid(folder);
    }
  });

  // ── Tray ──
  const tray = document.createElement("div");
  tray.className = "unified-tray";
  tray.id = trayId;

  const trayInner = document.createElement("div");
  trayInner.className = "unified-tray-inner";

  // Card Output Dir Row is now global (in thesis-strip). Removed from tray.



  // PDF checkbox grid placeholder
  const gridEl = document.createElement("div");
  gridEl.className = "pdf-checkbox-grid";
  gridEl.id = `${rowId}-grid`;
  trayInner.appendChild(gridEl);

  // File-status panel placeholder
  const statusPanel = document.createElement("div");
  statusPanel.className = "file-status-panel";
  statusPanel.id = `${rowId}-statuspanel`;
  statusPanel.style.display = "none";
  trayInner.appendChild(statusPanel);

  // Copy row
  const copyRow = document.createElement("div");
  copyRow.className = "tray-copy-row";
  const copyBtn = document.createElement("button");
  copyBtn.className = "btn btn-ghost";
  copyBtn.style.cssText = "padding:4px 12px;font-size:11px;";
  copyBtn.id = `${rowId}-copybtn`;
  copyBtn.textContent = hasDrive ? "📋 Copy Selected Drive Links" : "📋 Copy Selected Filenames";
  copyBtn.addEventListener("click", () => copyFolderLinks(thesisName));
  const copyNote = document.createElement("span");
  copyNote.className = "tray-copy-note";
  copyNote.textContent = hasDrive ? "Paste into NotebookLM Add Source" : "No Drive links — upload manually to NotebookLM";
  copyRow.appendChild(copyBtn);
  copyRow.appendChild(copyNote);
  trayInner.appendChild(copyRow);

  tray.appendChild(trayInner);
  row.appendChild(summary);
  row.appendChild(tray);
  return row;
}



window.copyFolderLinks = async function(thesisName) {
  const folder = state.thesisFolders.find(f => f.thesis_name === thesisName);
  if (!folder) return;
  const sel = _getPdfSelection(thesisName);
  const allPdfs = folder.pdfs ?? [];
  const selectedPdfs = allPdfs.filter(p => sel.has(p.file_name ?? p));
  const linked = selectedPdfs.filter(p => p.drive_link).map(p => p.drive_link);
  const filenames = selectedPdfs.map(p => p.file_name ?? p);
  const text = linked.length ? linked.join("\n") : filenames.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast(linked.length ? "Drive links copied (selected only)" : "Filenames copied (selected only)", "success");
  } catch (_) {
    toast("Copy failed — select manually", "error");
  }
};

// ── PDF checkbox grid renderer (3-column, replaces _renderPdfChips) ────────────

function _renderPdfCheckboxGrid(folder) {
  const thesisName = folder.thesis_name;
  const rowId = `uf-${thesisName.replace(/\W/g, "_")}`;
  const grid = $(`${rowId}-grid`);
  if (!grid) return;

  const allPdfs = folder.pdfs ?? [];
  const sel = _getPdfSelection(thesisName);
  const alreadyUploaded = _getAlreadyUploaded(thesisName);

  grid.innerHTML = "";

  for (const pdf of allPdfs) {
    const fname = pdf.file_name ?? pdf;
    const isUploaded = alreadyUploaded.has(fname);
    const isSelected = sel.has(fname);

    const item = document.createElement("div");
    item.className = `pdf-check-item ${isUploaded ? "pci-uploaded" : isSelected ? "pci-checked" : "pci-unchecked"}`;
    item.title = isUploaded
      ? "Already in notebook — will be skipped on re-upload"
      : isSelected ? "Selected — will be uploaded" : "Excluded — will NOT be uploaded";

    const box = document.createElement("span");
    box.className = "pci-box";
    box.textContent = (isSelected || isUploaded) ? "✓" : "";

    const nameEl = document.createElement("span");
    nameEl.className = "pci-name";
    if (pdf.drive_link) {
      nameEl.innerHTML = `<a href="${esc(pdf.drive_link)}" target="_blank" onclick="event.stopPropagation()">${esc(fname)}</a>`;
    } else {
      nameEl.textContent = fname;
    }

    item.appendChild(box);
    item.appendChild(nameEl);

    item.addEventListener("click", (e) => {
      if (e.target.tagName === "A") return;
      if (sel.has(fname)) sel.delete(fname);
      else sel.add(fname);
      _savePdfSelection(thesisName);
      _renderPdfCheckboxGrid(folder);
    });

    grid.appendChild(item);
  }

  // Update file-status panel
  _renderFileStatusPanel(folder, sel, alreadyUploaded);
}

// ── File-status panel (shared, referenced by _renderPdfCheckboxGrid) ──────────


function _renderFileStatusPanel(folder, sel, alreadyUploaded) {
  const rowId = `uf-${folder.thesis_name.replace(/\W/g, "_")}`;
  const panel = $(`${rowId}-statuspanel`);
  if (!panel) return;

  const allPdfs = (folder.pdfs ?? []).map(p => p.file_name ?? p);
  const hasNotebook = alreadyUploaded.size > 0;

  if (!hasNotebook) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "flex";

  // Compute categories
  const alreadyIn    = allPdfs.filter(f => alreadyUploaded.has(f));
  const newToUpload  = allPdfs.filter(f => !alreadyUploaded.has(f) && sel.has(f));
  const excluded     = allPdfs.filter(f => !sel.has(f));

  panel.innerHTML = `
    <div class="file-status-row">
      <span class="file-status-icon">✅</span>
      <span class="file-status-label">Already in notebook — will be skipped</span>
      <span class="file-status-count fsc-uploaded">${alreadyIn.length}</span>
    </div>
    <div class="file-status-row">
      <span class="file-status-icon">⬆</span>
      <span class="file-status-label">Selected — new, will be uploaded</span>
      <span class="file-status-count fsc-new">${newToUpload.length}</span>
    </div>
    <div class="file-status-row">
      <span class="file-status-icon">☐</span>
      <span class="file-status-label">Excluded by you</span>
      <span class="file-status-count fsc-excluded">${excluded.length}</span>
    </div>
  `;
}

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

// ── Thesis selector (reads from same localStorage as thesis_setup.js) ─────────

function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || "";
}

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem("spo_theses") || "[]"); } catch { return []; }
}

async function loadLibThesisSelector() {
  const sel = $("libThesisSelect");
  if (!sel) return;
  try {
    const list = await API.listTheses();
    const mapped = list.map(t => ({
      id: t.thesis_id,
      title: t.title || "Untitled",
      author: t.author || "",
    }));
    localStorage.setItem("spo_theses", JSON.stringify(mapped));
    const activeId = _activeThesisId();
    if (activeId && !mapped.find(t => t.id === activeId)) {
      localStorage.setItem("spo_active_thesis", "");
    }
    _renderThesisSelect(mapped);
  } catch (_) {
    _renderThesisSelect(_loadThesesIndex());
  }
}

function _renderThesisSelect(theses) {
  const sel = $("libThesisSelect");
  const activeId = _activeThesisId();
  sel.innerHTML = "";
  if (!theses.length) {
    sel.innerHTML = `<option value="">— No theses —</option>`;
    return;
  }
  for (const t of theses) {
    const opt = document.createElement("option");
    opt.value = t.id;
    opt.textContent = `${t.title} — ${t.author}`;
    if (t.id === activeId) opt.selected = true;
    sel.appendChild(opt);
  }
}

function onLibThesisChange(id) {
  localStorage.setItem("spo_active_thesis", id);
  actions.loadLibrary();
  loadThesisFolders(); // refresh Card 01 to show only the newly-active thesis
}

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
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

  // ── Card 02b: source card indexing ────────────────────────────────────────
  $("btnRunAllUnindexed").addEventListener("click", handleRunAllUnindexed);
  $("btnBatchConfirm").addEventListener("click", confirmBatch);
  $("btnBatchCancel").addEventListener("click", () => { $("batchConfirmModal").style.display = "none"; });
  $("btnRerunCancel").addEventListener("click", () => { $("rerunWarnModal").style.display = "none"; });
  $("btnGoToCard03").onclick = () => {
    $("rerunWarnModal").style.display = "none";
    $("card02").classList.add("active");
    setTimeout(() => {
      $("card02").scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  // ── Auth Banner ───────────────────────────────────────────────────────────
  const btnAuthAction = $("btnAuthAction");
  if (btnAuthAction) btnAuthAction.addEventListener("click", handleAuthAction);
  checkAuthOnLoad();

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

  // ── Thesis selector ───────────────────────────────────────────────────────
  await loadLibThesisSelector();
  const libSel = $("libThesisSelect");
  if (libSel) {
    libSel.addEventListener("change", e => {
      if (typeof onLibThesisChange === 'function') onLibThesisChange(e.target.value);
      loadGlobalCardDir();
    });
  }

  const btnSetDir = $("btnSetGlobalCardDir");
  if (btnSetDir) {
    btnSetDir.addEventListener("click", async () => {
      const defaultPath = state.globalCardOutputDir || "C:/Users/TUSHAR/Desktop/surgical prompt orchaestrator/a_synopsis/index_cards";
      btnSetDir.disabled = true;
      btnSetDir.textContent = "Browsing...";
      try {
        const result = await API.chooseFolder(defaultPath);
        const newPath = result.path;
        if (newPath && newPath.trim()) {
          await API.setCardOutputDir(newPath.trim());
          toast("Card output directory set", "success");
          await loadGlobalCardDir();
        }
      } catch (err) {
        toast(`Failed to set directory: ${err.message}`, "error");
      } finally {
        btnSetDir.disabled = false;
        btnSetDir.textContent = "✏️ Set Path";
      }
    });
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  actions.loadLibrary();
  loadGlobalCardDir();
  loadThesisFolders().then(_prefetchIndexStatuses);
}

window.addEventListener("storage", (e) => {
  if (e.key === "spo_active_thesis") {
    loadLibThesisSelector().then(() => actions.loadLibrary());
  }
});

document.addEventListener("DOMContentLoaded", init);

async function loadGlobalCardDir() {
  try {
    const res = await API.getCardOutputDir();
    state.globalCardOutputDir = res.card_output_dir || "";
    const el = $("globalCardOutputDir");
    if (el) el.value = state.globalCardOutputDir;
  } catch (err) {
    console.error("Failed to load global card dir", err);
  }
}

// =============================================================================
// CARD 02b — SOURCE CARD INDEXING
// Pre-fetch: populate indexState.statuses on page load so notebook IDs are
// available immediately — without waiting for an active polling cycle.
async function _prefetchIndexStatuses() {
  const names = state.thesisFolders.map(f => f.thesis_name);
  if (!names.length) return;
  try {
    const results = await _apiGet(
      `/source-index/status?thesis_names=${encodeURIComponent(names.join(","))}`
    );
    for (const r of results) {
      indexState.statuses[r.thesis_name] = r;
    }
    // Re-render both cards so notebook links appear immediately
    renderThesisFolders();
    renderIndexTable();
  } catch (_) {
    // Non-fatal — links will appear once the poller runs
  }
}
// =============================================================================

// ── API helpers ───────────────────────────────────────────────────────────────

const BASE = () => window.SPO_API_BASE || "";

async function _apiPost(path, body, thesisId = "") {
  const url = `${BASE()}${path}${thesisId ? `?thesis_id=${encodeURIComponent(thesisId)}` : ""}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function _apiGet(path) {
  const res = await fetch(`${BASE()}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function _apiDelete(path, thesisId = "") {
  const url = `${BASE()}${path}${thesisId ? `?thesis_id=${encodeURIComponent(thesisId)}` : ""}`;
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── State for Card 02b ────────────────────────────────────────────────────────

const indexState = {
  folders: [],            // from thesisFolders after loadThesisFolders
  statuses: {},           // { thesis_name: { status, ... } }
  pollerTimer: null,
  pendingBatchNames: [],  // names queued for batch confirm modal
};

// ── Render ────────────────────────────────────────────────────────────────────

// renderIndexTable is now a shim — all rendering goes through renderUnifiedTable.
function renderIndexTable() {
  renderUnifiedTable();
}


function _chipClass(status, isIndexed) {
  if (isIndexed && status === "idle") return "chip-done";
  switch (status) {
    case "done":                    return "chip-done";
    case "running":                 return "chip-running";
    case "warn":                    return "chip-warn";
    case "error":                   return "chip-error";
    case "waiting_for_manual_upload": return "chip-waiting";
    case "cancelled":               return "chip-cancelled";
    case "queued":                  return "chip-running";
    default:                        return "chip-idle";
  }
}

function _chipLabel(status, isIndexed) {
  if (isIndexed && status === "idle") return "✓ Indexed";
  switch (status) {
    case "done":                    return "✓ Indexed";
    case "running":                 return "⚙ Running…";
    case "warn":                    return "⚠ Warn";
    case "error":                   return "✕ Error";
    case "waiting_for_manual_upload": return "⏳ Upload needed";
    case "cancelled":               return "— Cancelled";
    case "queued":                  return "⏳ Queued";
    default:                        return "⬜ idle";
  }
}

function _updateIndexPill() {
  const pill = $("indexPill");
  const total    = state.thesisFolders.length;
  const indexed  = state.thesisFolders.filter(f => {
    const s = indexState.statuses[f.thesis_name]?.status;
    return s === "done" || s === "warn" || f.imported;
  }).length;
  if (!total) { pill.textContent = "—"; pill.className = "pill pill-idle"; return; }
  pill.textContent = `${indexed} / ${total} indexed`;
  pill.className = indexed === total ? "pill pill-done" : "pill pill-active";
}

// ── Poller ────────────────────────────────────────────────────────────────────

function _startPoller() {
  if (indexState.pollerTimer) return; // already running
  const running = state.thesisFolders.some(f => {
    const s = indexState.statuses[f.thesis_name]?.status;
    return s === "running" || s === "queued";
  });
  if (!running) return;

  indexState.pollerTimer = setInterval(async () => {
    const allNames = state.thesisFolders.map(f => f.thesis_name);
    if (!allNames.length) return;
    try {
      const results = await _apiGet(
        `/source-index/status?thesis_names=${encodeURIComponent(allNames.join(","))}`
      );
      let anyActive = false;
      for (const r of results) {
        indexState.statuses[r.thesis_name] = r;
        if (r.status === "running" || r.status === "queued") anyActive = true;
      }
      renderIndexTable();

      if (!anyActive) {
        clearInterval(indexState.pollerTimer);
        indexState.pollerTimer = null;
        // Refresh Card 03 when any jobs completed
        await actions.loadLibrary();
        toast("Source indexing complete", "success");
      }
    } catch (err) {
      // silently ignore transient poll errors
    }
  }, 3000);
}

function _stopPoller() {
  if (indexState.pollerTimer) {
    clearInterval(indexState.pollerTimer);
    indexState.pollerTimer = null;
  }
}

// ── Handlers ──────────────────────────────────────────────────────────────────

async function handleRunSingle(thesisName) {
  const thesisId = _activeThesisId();
  
  // Prompt for card output dir if missing
  if (!state.globalCardOutputDir) {
    toast("Please set the Card Output Path for the active thesis first.", "error");
    return;
  }

  const included = [..._getPdfSelection(thesisName)];
  if (included.length === 0) {
    toast(`${thesisName}: no PDFs selected — check at least one PDF before running`, "error");
    return;
  }
  try {
    await _apiPost("/source-index/run", { thesis_name: thesisName, included_files: included }, thesisId);
    indexState.statuses[thesisName] = { ...indexState.statuses[thesisName], status: "queued" };
    renderIndexTable();
  } catch (err) {
    if (err.message.includes("409")) {
      toast(`Already running: ${thesisName}`, "error");
    } else {
      toast(`Run failed: ${err.message}`, "error");
      if (err.message.includes("NLMAuthError") || err.message.includes("credentials") || err.message.includes("initialize")) {
        checkAuthOnLoad();
      }
    }
  }
}

async function handleStop(thesisName) {
  const thesisId = _activeThesisId();
  try {
    await _apiDelete(`/source-index/stop/${encodeURIComponent(thesisName)}`, thesisId);
    indexState.statuses[thesisName] = { ...indexState.statuses[thesisName], status: "cancelled" };
    renderIndexTable();
    toast(`Stopped: ${thesisName}`, "info");
  } catch (err) {
    toast(`Stop failed: ${err.message}`, "error");
  }
}

function handleRunAllUnindexed() {
  const unindexed = state.thesisFolders.filter(f => {
    const s = indexState.statuses[f.thesis_name]?.status;
    return !s || s === "idle" || s === "error" || s === "cancelled" || s === "waiting_for_manual_upload";
  }).filter(f => !f.imported);

  if (!unindexed.length) {
    toast("All folders are already indexed", "info");
    return;
  }

  const totalPdfs = unindexed.reduce((n, f) => n + (f.pdfs?.length ?? 0), 0);

  $("batchFolderCount").textContent = unindexed.length;
  $("batchPdfCount").textContent    = totalPdfs;
  indexState.pendingBatchNames      = unindexed.map(f => f.thesis_name);
  $("batchConfirmModal").style.display = "flex";
}

async function confirmBatch() {
  $("batchConfirmModal").style.display = "none";
  const thesisId = _activeThesisId();
  const names = indexState.pendingBatchNames;
  if (!names.length) return;

  // Check if global card dir is set
  if (!state.globalCardOutputDir) {
    toast(`Run cancelled: Please set Card Output Path for the active thesis first.`, "error");
    return;
  }

  // Build per-folder selection map
  const included_files_map = {};
  for (const name of names) {
    included_files_map[name] = [..._getPdfSelection(name)];
  }

  try {
    const result = await _apiPost("/source-index/run-batch", { thesis_names: names, included_files_map }, thesisId);
    for (const job of (result.jobs || [])) {
      indexState.statuses[job.thesis_name] = { status: "queued" };
    }
    renderIndexTable();
    toast(`Batch started — ${names.length} folders queued`, "success");
  } catch (err) {
    toast(`Batch failed: ${err.message}`, "error");
    if (err.message.includes("NLMAuthError") || err.message.includes("credentials") || err.message.includes("initialize")) {
      checkAuthOnLoad();
    }
  }
}

function showRerunWarning(thesisName, groupId) {
  $("rerunGroupId").textContent = groupId;
  $("rerunWarnModal").style.display = "flex";
  // The "Go to Card 03" btn is already wired in init().
  // We don't fire the run here — user must manually dismiss, delete old group, then re-run.
}

function scrollToGroup(groupId) {
  $("card02").classList.add("active");
  const el = $(`group-${groupId}`);
  if (!el) {
    toast(`Group not found in Card 02 — it may still be loading`, "info");
    return;
  }
  setTimeout(() => {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("open");
  }, 100);
}

// ── Hook into existing loadThesisFolders ─────────────────────────────────────
// After thesis folders load (Card 02), also refresh index table

const _origLoadThesisFolders = loadThesisFolders;
// Redefine to also refresh Card 02b
// (function-level reassignment used since module scope prohibits let/const redeclaration)
window._refreshIndexTable = function() {
  // state.thesisFolders is already updated when called — just re-render
  renderIndexTable();
};

// ── Auth Banner Logic ────────────────────────────────────────────────────────

let authPollTimer = null;

async function checkAuthOnLoad() {
  try {
    const res = await API.nlmStatus();
    if (!res.ok) {
      showAuthBanner("login");
    } else {
      hideAuthBanner();
    }
  } catch (err) {
    showAuthBanner("error", err.message);
  }
}

function showAuthBanner(phase, msg = "") {
  const banner = $("nlmAuthBanner");
  if (!banner) return;
  const text = $("authBannerText");
  const btn = $("btnAuthAction");
  
  banner.style.display = "flex";
  
  if (phase === "login") {
    text.textContent = "NotebookLM auth missing or expired. You must log in before running indexing.";
    btn.textContent = "Start Login";
    btn.dataset.action = "start";
    btn.disabled = false;
  } else if (phase === "confirm") {
    text.textContent = "A browser window has opened. Complete login there, then click Confirm.";
    btn.textContent = "Confirm Login";
    btn.dataset.action = "confirm";
    btn.disabled = false;
  } else if (phase === "polling") {
    text.textContent = "Waiting for login process to finish and save state...";
    btn.textContent = "Waiting...";
    btn.disabled = true;
  } else if (phase === "error") {
    text.textContent = `Auth error: ${msg}`;
    btn.textContent = "Retry Login";
    btn.dataset.action = "start";
    btn.disabled = false;
  }
}

function hideAuthBanner() {
  const banner = $("nlmAuthBanner");
  if (banner) banner.style.display = "none";
  if (authPollTimer) clearInterval(authPollTimer);
}

async function handleAuthAction() {
  const btn = $("btnAuthAction");
  const action = btn.dataset.action;
  
  try {
    if (action === "start") {
      btn.disabled = true;
      btn.textContent = "Starting...";
      
      const res = await API.nlmAuthStart();
      if (!res.ok) throw new Error(res.error || "Failed to start auth process");
      
      showAuthBanner("confirm");
      startAuthPoller();
    } else if (action === "confirm") {
      showAuthBanner("polling");
      
      const res = await API.nlmAuthConfirm();
      if (!res.ok) throw new Error(res.error || "Failed to confirm login");
      
      if (authPollTimer) clearInterval(authPollTimer);
      await checkAuthOnLoad();
      toast("Login complete", "success");
    }
  } catch (err) {
    showAuthBanner("error", err.message);
  }
}

function startAuthPoller() {
  if (authPollTimer) clearInterval(authPollTimer);
  authPollTimer = setInterval(async () => {
    try {
      const status = await API.nlmAuthStatus();
      if (status.phase === "error") {
        clearInterval(authPollTimer);
        showAuthBanner("error", status.message || "Subprocess crashed.");
      }
    } catch (e) {
      // ignore transient
    }
  }, 2000);
}


