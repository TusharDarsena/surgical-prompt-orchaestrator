/**
 * write_section.js
 *
 * Four layers — each only calls the one below:
 *   handlers  →  actions  →  state  →  render
 *
 * Plus a poller that drives run-state updates while any subtopic is running.
 */

import * as API from "./api.js";

// ─────────────────────────────────────────────────────────────────────────────
// STATE  —  single source of truth, never mutated directly outside this section
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  chapterId: null,   // currently selected chapter
  chapters: [],     // full chapter list from server
  subtopics: [],     // subtopics of selected chapter

  // active subtopic = the one whose draft is shown in card-03
  activeSubtopicId: null,

  // config (card-01) — shared by all runs in the chapter
  wordCount: 750,
  styleNotes: "",
  uploadMethod: "drive",

  // per-subtopic run states:  subtopicId → nlm_state response
  runStates: {},

  // per-subtopic drafts:      subtopicId → string
  drafts: {},

  // resolved sources for the active subtopic (from compile meta)
  sources: [],

  // consistency chain for the chapter
  chain: [],

  // active batch ID — set when runAllIdle fires, cleared when batch completes
  batchId: null,

  // saved consistency text for the active subtopic
  consistencyText: null,
};

function getActiveSubtopic() {
  return state.subtopics.find(s => s.subtopic_id === state.activeSubtopicId) ?? null;
}

function getRunState(subtopicId) {
  return state.runStates[subtopicId] ?? { status: "idle" };
}

// ─────────────────────────────────────────────────────────────────────────────
// TOAST
// ─────────────────────────────────────────────────────────────────────────────

function toast(msg, type = "info", duration = 3000) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ─────────────────────────────────────────────────────────────────────────────
// CLIPBOARD
// ─────────────────────────────────────────────────────────────────────────────

async function copyToClipboard(text, label = "Copied!") {
  try {
    await navigator.clipboard.writeText(text);
    toast(`✓ ${label}`, "success");
  } catch (_) {
    toast("Copy failed — select manually.", "error");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// RENDER  —  pure DOM updates from state, no side effects
// ─────────────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

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
  state.chapters = [];
  state.subtopics = [];
  state.chapterId = null;
  state.activeSubtopicId = null;
  state.runStates = {};
  state.drafts = {};
  state.sources = [];
  state.chain = [];
  state.batchId = null;
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

function renderContextPills() {
  const sub = getActiveSubtopic();
  $("pillSources").textContent = sub?.source_ids?.length ?? "—";
  $("pillPages").textContent = sub?.estimated_pages ?? "—";

  const done = state.chain.length;
  $("pillDone").textContent = done;
}

function renderSubtopicSelect() {
  const sel = $("subtopicSelect");
  sel.innerHTML = "";

  if (!state.subtopics.length) {
    sel.innerHTML = `<option value="">— No subtopics —</option>`;
    return;
  }

  for (const s of state.subtopics) {
    const opt = document.createElement("option");
    opt.value = s.subtopic_id;
    opt.textContent = `${s.number} — ${s.title}`;
    if (s.subtopic_id === state.activeSubtopicId) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderRunTable() {
  const tbody = $("runTableBody");
  tbody.innerHTML = "";

  for (const sub of state.subtopics) {
    const rs = getRunState(sub.subtopic_id);
    const status = rs.status ?? "idle";   // idle | running | done | error
    const hasDraft = Boolean(state.drafts[sub.subtopic_id]);

    const row = document.createElement("div");
    row.className = `run-row state-${status}`;
    row.dataset.subtopicId = sub.subtopic_id;

    // Subtopic name column
    const nameCol = document.createElement("div");
    nameCol.className = "subtopic-name";

    const nameLine = document.createElement("div");
    nameLine.innerHTML =
      `<span class="sub-num">${sub.number}</span><span class="sub-label">${_esc(sub.title)}</span>`;
    nameCol.appendChild(nameLine);

    if (status === "running") {
      const note = document.createElement("div");
      note.className = "run-status-note";
      note.textContent = rs.sources_uploaded?.length
        ? `Uploading… (${rs.sources_uploaded.length} done)`
        : "Starting…";
      nameCol.appendChild(note);
    }
    if (status === "error") {
      const note = document.createElement("div");
      note.className = "run-status-note";
      note.style.color = "#f87171";
      note.textContent = rs.error ?? "Error";
      nameCol.appendChild(note);
    }
    if (status === "waiting_for_manual_upload") {
      const note = document.createElement("div");
      note.className = "run-status-note";
      note.style.color = "#d97706";
      note.textContent = "Waiting for manual upload...";
      if (rs.missing_sources && rs.missing_sources.length > 0) {
        const missing = document.createElement("div");
        missing.style.fontSize = "10px";
        missing.style.color = "var(--muted)";
        missing.style.marginTop = "4px";
        
        // Handle new object structure for missing_sources
        rs.missing_sources.forEach(s => {
          const name = typeof s === "string" ? s : s.file_name;
          const link = typeof s === "object" ? s.drive_link : null;
          
          const span = document.createElement("span");
          span.style.display = "block";
          span.textContent = `• ${name} `;
          if (link) {
            const a = document.createElement("a");
            a.href = link;
            a.target = "_blank";
            a.textContent = "↗ Drive";
            a.style.color = "var(--primary)";
            a.style.textDecoration = "underline";
            a.style.marginLeft = "4px";
            span.appendChild(a);
          }
          missing.appendChild(span);
        });
        note.appendChild(missing);
      }
      nameCol.appendChild(note);
    }

    // Action column
    const actCol = document.createElement("div");
    actCol.className = "run-action-cell";

    if (status === "done" && rs.prompt_2) {
      const badge = document.createElement("span");
      badge.className = "gemini-badge";
      badge.textContent = "📋 Gemini";
      badge.title = "Copy Stage 2 Gemini prompt";
      badge.dataset.prompt2 = rs.prompt_2;
      badge.addEventListener("click", () => {
        copyToClipboard(rs.prompt_2, "Stage 2 Gemini prompt copied");
      });
      actCol.appendChild(badge);
    }

    // copy prompt icon — always visible
    const cpBtn = document.createElement("button");
    cpBtn.className = "copy-icon-btn";
    cpBtn.title = "Copy prompt manually";
    cpBtn.textContent = "📋";
    cpBtn.addEventListener("click", () => actions.copyPromptForSubtopic(sub.subtopic_id));
    actCol.appendChild(cpBtn);

    if (status === "idle" || status === "error") {
      // run button
      const runBtn = document.createElement("button");
      runBtn.className = "btn btn-run";
      runBtn.textContent = "▶ Run";
      runBtn.addEventListener("click", () => actions.runSubtopic(sub.subtopic_id));
      actCol.appendChild(runBtn);
    }

    if (status === "waiting_for_manual_upload") {
      // resume button
      const resumeBtn = document.createElement("button");
      resumeBtn.className = "btn btn-run";
      resumeBtn.textContent = "⟳ Sync & Resume";
      resumeBtn.title = "Click after you manually add the missing PDF to NotebookLM";
      resumeBtn.addEventListener("click", () => actions.runSubtopic(sub.subtopic_id));
      actCol.appendChild(resumeBtn);
    }

    if (status === "running") {
      const stopBtn = document.createElement("button");
      stopBtn.className = "btn btn-danger";
      stopBtn.style.cssText = "padding:4px 10px;font-size:11px;";
      stopBtn.textContent = "Stop";
      stopBtn.addEventListener("click", () => actions.stopSubtopic(sub.subtopic_id));
      actCol.appendChild(stopBtn);
    }

    if (status === "done") {
      const rerunBtn = document.createElement("button");
      rerunBtn.className = "btn btn-ghost";
      rerunBtn.style.cssText = "padding:4px 10px;font-size:11px;";
      rerunBtn.textContent = "Re-run";
      rerunBtn.addEventListener("click", () => actions.runSubtopic(sub.subtopic_id));
      actCol.appendChild(rerunBtn);
    }

    // ↗ open draft button
    const openBtn = document.createElement("button");
    openBtn.className = "open-btn";
    openBtn.title = hasDraft ? "Open draft in editor" : "No draft yet";
    openBtn.textContent = "↗";
    if (!hasDraft) openBtn.setAttribute("disabled", "true");
    openBtn.addEventListener("click", () => actions.openDraft(sub.subtopic_id));
    actCol.appendChild(openBtn);

    row.appendChild(nameCol);
    row.appendChild(actCol);
    tbody.appendChild(row);
  }
}

function renderDraftCard() {
  const sub = getActiveSubtopic();
  const text = sub ? (state.drafts[sub.subtopic_id] ?? "") : "";

  $("draftSubtopicPill").textContent = sub
    ? `${sub.number} active`
    : "no subtopic";

  const ta = $("draftTextarea");
  if (ta !== document.activeElement) {   // don't stomp user edits
    ta.value = text;
  }
  _updateWordCount();
}

function renderSources() {
  const list = $("sourcesList");
  const head = $("sourcesHead");
  const sources = state.sources;

  const uniqueWorks = new Set(sources.map(s => s.source_id)).size;
  const fileCount = sources.filter(s => s.file_name || s.drive_link).length;

  $("sourcesCount").textContent = uniqueWorks;
  $("sourcesCountSub").textContent =
    `work${uniqueWorks !== 1 ? "s" : ""} · ${fileCount} file${fileCount !== 1 ? "s" : ""}`;

  list.innerHTML = "";

  if (!sources.length) {
    list.innerHTML = `<p class="sp-empty">Compile a prompt to resolve sources.</p>`;
    return;
  }

  for (const s of sources) {
    const entry = document.createElement("div");
    entry.className = "source-entry";

    const btn = document.createElement("button");
    btn.className = "source-open-btn";
    btn.title = s.drive_link ? "Open in Drive" : s.file_name ? "Open file" : "No link";
    btn.textContent = "↗";
    if (!s.drive_link && !s.file_name) btn.classList.add("no-link");
    btn.addEventListener("click", () => {
      if (s.drive_link) window.open(s.drive_link, "_blank");
    });

    const info = document.createElement("div");
    info.className = "source-info";

    const name = document.createElement("span");
    name.className = "source-name";
    name.textContent = s.source_id;
    info.appendChild(name);

    const tags = document.createElement("div");
    tags.className = "source-tags";
    if (s.chapter_id) {
      const tag = document.createElement("span");
      tag.className = "stag";
      tag.textContent = s.chapter_id;
      tags.appendChild(tag);
    }
    info.appendChild(tags);

    entry.appendChild(btn);
    entry.appendChild(info);
    list.appendChild(entry);
  }
}

function renderConsistencyCard() {
  const saved = $("consistencySavedBox");
  const text = state.consistencyText;
  if (text) {
    saved.innerHTML = `
      <div class="summary-saved-label">Saved summary</div>
      <div class="summary-saved-text">${_esc(text)}</div>`;
  } else {
    saved.innerHTML = `<div class="summary-saved-text">No summary saved yet for this subtopic.</div>`;
  }
}

// Card pill counters for card-02
function renderGeneratePill() {
  const done = state.subtopics.filter(s => getRunState(s.subtopic_id).status === "done").length;
  const total = state.subtopics.length;
  const pill = $("generatePill");
  if (!total) { pill.textContent = "—"; pill.className = "pill pill-idle"; return; }
  pill.textContent = `${done} / ${total} done`;
  pill.className = done === total ? "pill pill-done" : done > 0 ? "pill pill-active" : "pill pill-idle";
}

// ─────────────────────────────────────────────────────────────────────────────
// CARD ACCORDION
// ─────────────────────────────────────────────────────────────────────────────

function toggleCard(id) {
  const card = document.getElementById(id);
  const isActive = card.classList.contains("active");
  // close all
  document.querySelectorAll(".card").forEach(c => c.classList.remove("active"));
  if (!isActive) card.classList.add("active");
}

// ─────────────────────────────────────────────────────────────────────────────
// ACTIONS  —  async operations that mutate state then call render
// ─────────────────────────────────────────────────────────────────────────────

const actions = {

  async selectChapter(chapterId) {
    const chapter = state.chapters.find(c => c.chapter_id === chapterId);
    if (!chapter) return;

    state.chapterId = chapterId;
    state.subtopics = chapter.subtopics ?? [];
    state.runStates = {};
    state.drafts = {};
    state.batchId = null;   // ← ADD: clear any in-flight batch on chapter switch
    state.activeSubtopicId = state.subtopics[0]?.subtopic_id ?? null;

    // Load sources from active subtopic's source_ids
    const firstSub = state.subtopics[0];
    state.sources = (firstSub?.source_ids ?? []).map(s => ({
      ...s,
      file_name: null,
      drive_link: null
    }));

    // Load chain
    try {
      const res = await API.getChainForChapter(chapterId);
      state.chain = res.chain ?? [];
    } catch (_) { state.chain = []; }

    // Load run states + drafts for all subtopics concurrently
    await Promise.allSettled(
      state.subtopics.map(s => actions._refreshSubtopicData(s.subtopic_id))
    );

    renderSubtopicSelect();
    renderRunTable();
    renderDraftCard();
    renderContextPills();
    renderGeneratePill();

    // Show sources from source_ids (resolved after compile if needed)
    renderSources();
    renderConsistencyCard();

    // Kick off polling if any run is active
    poller.sync();
  },

  async selectActiveSubtopic(subtopicId) {
    state.activeSubtopicId = subtopicId;

    // Load sources from selected subtopic's source_ids
    const sub = getActiveSubtopic();
    state.sources = (sub?.source_ids ?? []).map(s => ({
      ...s,
      file_name: null,
      drive_link: null
    }));

    // Load draft if not cached
    if (state.drafts[subtopicId] === undefined) {
      await actions._loadDraft(subtopicId);
    }

    // Load consistency for this subtopic
    await actions._loadConsistency(subtopicId);

    renderSubtopicSelect();
    renderDraftCard();
    renderContextPills();
    renderSources();
    renderConsistencyCard();
  },

  async _refreshSubtopicData(subtopicId) {
    const [runRes, draftRes] = await Promise.allSettled([
      API.nlmState(state.chapterId, subtopicId),
      API.getDraft(state.chapterId, subtopicId),
    ]);
    if (runRes.status === "fulfilled")
      state.runStates[subtopicId] = runRes.value;
    if (draftRes.status === "fulfilled")
      state.drafts[subtopicId] = draftRes.value?.text ?? null;
    else
      state.drafts[subtopicId] = null;
  },

  async _loadDraft(subtopicId) {
    try {
      const res = await API.getDraft(state.chapterId, subtopicId);
      state.drafts[subtopicId] = res?.text ?? null;
    } catch (_) {
      state.drafts[subtopicId] = null;
    }
  },

  async _loadConsistency(subtopicId) {
    // Find in the already-loaded chain
    const entry = state.chain.find(e => e.subtopic_id === subtopicId);
    state.consistencyText = entry?.core_argument_made ?? null;
  },

  async runSubtopic(subtopicId) {
    try {
      await API.nlmRun(
        state.chapterId,
        subtopicId,
        state.wordCount || null,
        state.styleNotes || null,
        state.uploadMethod,
      );
      state.runStates[subtopicId] = { status: "running" };
      renderRunTable();
      renderGeneratePill();
      poller.start();
      toast("Run started", "info");
    } catch (err) {
      toast(`Run failed: ${err.message}`, "error");
    }
  },

  async runAllIdle() {
    const idle = state.subtopics.filter(
      s => {
        const st = getRunState(s.subtopic_id).status;
        return st === "idle" || st === "error";
      }
    );
    if (!idle.length) { toast("No idle or failed subtopics", "info"); return; }

    const idleIds = idle.map(s => s.subtopic_id);

    try {
      const res = await API.nlmRunBatch(
        state.chapterId,
        idleIds,
        state.wordCount || null,
        state.styleNotes || null,
        state.uploadMethod,
      );

      // Store batch_id so the poller knows to use the batch endpoint
      state.batchId = res.batch_id;

      // Mark all idle subtopics as running optimistically
      for (const id of idleIds) {
        state.runStates[id] = { status: "running", batch_id: res.batch_id };
      }

      renderRunTable();
      renderGeneratePill();
      poller.start();
      toast(`Batch started — ${idleIds.length} subtopics`, "info");
    } catch (err) {
      toast(`Batch failed: ${err.message}`, "error");
    }
  },

  async stopSubtopic(subtopicId) {
    try {
      await API.nlmDeleteNotebook(state.chapterId, subtopicId);
      state.runStates[subtopicId] = { status: "idle" };
      renderRunTable();
      renderGeneratePill();
      toast("Run stopped", "info");
    } catch (err) {
      toast(`Could not stop: ${err.message}`, "error");
    }
  },

  openDraft(subtopicId) {
    state.activeSubtopicId = subtopicId;
    renderSubtopicSelect();
    renderDraftCard();
    // Open card-03
    document.querySelectorAll(".card").forEach(c => c.classList.remove("active"));
    document.getElementById("card03").classList.add("active");
  },

  async saveDraft() {
    const text = $("draftTextarea").value.trim();
    if (!text) { toast("Draft is empty", "error"); return; }
    try {
      await API.saveDraft(state.chapterId, state.activeSubtopicId, text);
      state.drafts[state.activeSubtopicId] = text;
      renderRunTable();   // refresh open-btn enabled state
      toast("Draft saved", "success");
    } catch (err) {
      toast(`Save failed: ${err.message}`, "error");
    }
  },
  // NEW:
  async clearDraft() {
    if (!confirm("Clear this draft? This cannot be undone.")) return;
    try {
      await API.deleteDraft(state.chapterId, state.activeSubtopicId);
      state.drafts[state.activeSubtopicId] = null;
      state.runStates[state.activeSubtopicId] = { status: "idle" };
      $("draftTextarea").value = "";
      _updateWordCount();
      renderRunTable();
      renderGeneratePill();
      toast("Draft cleared", "info");
    } catch (err) {
      toast(`Clear failed: ${err.message}`, "error");
    }
  },

  async copyPromptForSubtopic(subtopicId) {
    try {
      const res = await API.compilePrompt(
        state.chapterId, subtopicId,
        state.wordCount || null,
        state.styleNotes || null,
      );
      const text = res.prompt_1 ?? res.prompt ?? "";
      await copyToClipboard(text, "Prompt 1 copied");
      // Also update sources panel if this is the active subtopic
      if (subtopicId === state.activeSubtopicId) {
        state.sources = res.meta?.required_sources ?? [];
        renderSources();
      }
    } catch (err) {
      toast(`Compile failed: ${err.message}`, "error");
    }
  },

  async generateConsistencyPrompt() {
    try {
      const res = await API.compilePrompt(
        state.chapterId, state.activeSubtopicId,
        state.wordCount || null,
        state.styleNotes || null,
      );
      const text = res.prompt_1 ?? res.prompt ?? "";
      await copyToClipboard(text, "Consistency prompt copied");
    } catch (err) {
      toast(`Failed: ${err.message}`, "error");
    }
  },

};

// ─────────────────────────────────────────────────────────────────────────────
// POLLER  —  polls run state for all subtopics while any is running
// ─────────────────────────────────────────────────────────────────────────────

const poller = {
  _timer: null,
  _interval: 3000,

  start() {
    if (this._timer) return;
    this._timer = setInterval(() => this._tick(), this._interval);
  },

  stop() {
    if (!this._timer) return;
    clearInterval(this._timer);
    this._timer = null;
  },

  // Called after chapter load — start only if needed
  sync() {
    const anyRunning = state.subtopics.some(
      s => getRunState(s.subtopic_id).status === "running"
    );
    anyRunning ? this.start() : this.stop();
  },

  async _tick() {
    if (!state.chapterId || !state.subtopics.length) { this.stop(); return; }

    // ── Batch mode: one request covers all subtopics ──────────────────────────
    if (state.batchId) {
      let batchRes;
      try {
        batchRes = await API.nlmBatchState(state.batchId);
      } catch (_) {
        return; // network blip — try again next tick
      }

      // Update each subtopic's runState from the batch response
      for (const snap of batchRes.subtopics ?? []) {
        const prev = getRunState(snap.subtopic_id).status;
        state.runStates[snap.subtopic_id] = {
          ...state.runStates[snap.subtopic_id],
          status: snap.status,
          error: snap.error,
          sources_uploaded: snap.sources_uploaded,
          sources_failed: snap.sources_failed,
          missing_sources: snap.missing_sources, // New sync status property
          batch_id: state.batchId,
        };

        // When a subtopic within the batch completes, auto-load its draft
        if (prev === "running" && snap.status === "done") {
          await actions._loadDraft(snap.subtopic_id);
          if (snap.subtopic_id === state.activeSubtopicId) renderDraftCard();
          const sub = state.subtopics.find(s => s.subtopic_id === snap.subtopic_id);
          if (sub) toast(`✓ ${sub.number} ${sub.title} — draft saved`, "success", 5000);
        }
      }

      renderRunTable();
      renderGeneratePill();

      // Stop polling and clear batchId when the entire batch is terminal
      const batchDone = batchRes.status === "done" || batchRes.status === "error";
      if (batchDone) {
        state.batchId = null;
        this.stop();
        if (batchRes.status === "done") {
          toast(`Batch complete — ${batchRes.progress?.done ?? "?"} subtopics done`, "success", 6000);
        } else {
          const errCount = batchRes.progress?.error ?? 0;
          toast(`Batch finished with ${errCount} error(s) — check individual subtopics`, "error", 7000);
        }
      }
      return;
    }

    // ── Solo mode: poll each running subtopic individually (unchanged) ─────────
    const running = state.subtopics.filter(
      s => getRunState(s.subtopic_id).status === "running"
    );
    if (!running.length) { this.stop(); return; }

    await Promise.allSettled(
      running.map(async s => {
        const rs = await API.nlmState(state.chapterId, s.subtopic_id);
        const prev = getRunState(s.subtopic_id).status;
        state.runStates[s.subtopic_id] = rs;

        if (prev === "running" && rs.status === "done") {
          await actions._loadDraft(s.subtopic_id);
          if (s.subtopic_id === state.activeSubtopicId) renderDraftCard();
          toast(`✓ ${s.number} ${s.title} — draft saved`, "success", 5000);
        }
      })
    );

    renderRunTable();
    renderGeneratePill();
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

function _esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _updateWordCount() {
  const text = $("draftTextarea")?.value ?? "";
  const wc = text.trim() ? text.trim().split(/\s+/).length : 0;
  $("wordCount").textContent = `~${wc.toLocaleString()} words`;
}

// ─────────────────────────────────────────────────────────────────────────────
// INIT  —  wire up DOM events and boot from server-rendered data
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  // Chapters are server-rendered into window.SPO_CHAPTERS by the template
  state.chapters = window.SPO_CHAPTERS ?? [];

  // ── Chapter select ────────────────────────────────────────────────────────
  $("chapterSelect").addEventListener("change", e => {
    actions.selectChapter(e.target.value);
  });

  // ── Subtopic select (active draft target) ─────────────────────────────────
  $("subtopicSelect").addEventListener("change", e => {
    actions.selectActiveSubtopic(e.target.value);
  });

  // ── Config (card-01) ──────────────────────────────────────────────────────
  $("btnWcMinus").addEventListener("click", () => {
    state.wordCount = Math.max(0, state.wordCount - 100);
    $("wcValue").textContent = state.wordCount;
  });
  $("btnWcPlus").addEventListener("click", () => {
    state.wordCount = Math.min(5000, state.wordCount + 100);
    $("wcValue").textContent = state.wordCount;
  });
  $("styleNotesInput").addEventListener("input", e => {
    state.styleNotes = e.target.value;
  });
  $("uploadMethodSelect").addEventListener("change", e => {
    state.uploadMethod = e.target.value;
  });

  // ── Card accordion headers ────────────────────────────────────────────────
  document.querySelectorAll(".card-header[data-card]").forEach(header => {
    header.addEventListener("click", () => toggleCard(header.dataset.card));
  });

  // ── Generate (card-02) ───────────────────────────────────────────────────
  $("btnCheckCreds").addEventListener("click", async () => {
    const statusEl = $("credStatus");
    statusEl.textContent = "Checking...";
    try {
      const res = await API.nlmStatus();
      if (res.ok) {
        statusEl.textContent = "✅ Ready";
        statusEl.style.color = "var(--success)";
      } else {
        statusEl.textContent = "❌ Not configured";
        statusEl.style.color = "#f87171";
      }
    } catch (err) {
      statusEl.textContent = "❌ Error";
      statusEl.style.color = "#f87171";
    }
  });
  $("btnRunAll").addEventListener("click", () => actions.runAllIdle());

  // ── Draft (card-03) ──────────────────────────────────────────────────────
  $("draftTextarea").addEventListener("input", _updateWordCount);
  $("btnSaveDraft").addEventListener("click", () => actions.saveDraft());
  $("btnClearDraft").addEventListener("click", () => actions.clearDraft());

  // ── Copy all source links ─────────────────────────────────────────────────
  $("btnCopyAllLinks")?.addEventListener("click", async () => {
    if (!state.chapterId || !state.activeSubtopicId) return;
    const res = await API.compilePrompt(state.chapterId, state.activeSubtopicId, state.wordCount || null, state.styleNotes || null);
    const sources = res.meta?.required_sources ?? [];
    state.sources = sources;
    renderSources();
    const links = sources.filter(s => s.drive_link).map(s => s.drive_link);
    if (links.length) copyToClipboard(links.join("\n"), `${links.length} link(s) copied`);
    else toast("No links found", "info");
  });

  // ── Consistency (card-04) ────────────────────────────────────────────────
  $("btnGenerateConsistency").addEventListener("click", () => actions.generateConsistencyPrompt());

  // ── Boot ──────────────────────────────────────────────────────────────────
  // ── Thesis selector ───────────────────────────────────────────────────────
  loadWriteThesisSelector();
  const writeThesisSel = $("writeThesisSelect");
  if (writeThesisSel) writeThesisSel.addEventListener("change", e => onWriteThesisChange(e.target.value));

  // ── Load chapters client-side (thesis-aware) ──────────────────────────────
  await loadChaptersFromServer();

  // ── Manual Sync Buttons ───────────────────────────────────────────────────
  $("btnSyncResume")?.addEventListener("click", async () => {
    try {
      $("btnSyncResume").disabled = true;
      $("btnSyncResume").textContent = "⏳...";
      
      // Find all subtopics in the CURRENT chapter that are paused
      const pausedIds = state.subtopics
        .filter(s => getRunState(s.subtopic_id).status === "waiting_for_manual_upload")
        .map(s => s.subtopic_id);
      
      if (pausedIds.length === 0) {
        toast("No paused runs to resume.", "info");
      } else {
        toast(`Resuming ${pausedIds.length} subtopic(s)...`, "info");
        for (const sid of pausedIds) {
          actions.runSubtopic(sid);
        }
      }
    } catch (err) {
      toast(`Resume failed: ${err.message}`, "error");
    } finally {
      $("btnSyncResume").disabled = false;
      $("btnSyncResume").textContent = "🔗 Sync & Resume";
    }
  });

  $("btnRefreshChapters")?.addEventListener("click", () => {
    loadChaptersFromServer();
    toast("Chapter list refreshed.", "success");
  });

  // ── Google Docs ───────────────────────────────────────────────────────────
  await _gdocsInit();

  $("btnConnectGDocs")?.addEventListener("click", () => {
    window.open("/gdocs/auth", "_blank", "width=600,height=700");
    _gdocsPollConnection();
  });

  $("btnExportToGDocs")?.addEventListener("click", () => actions.exportToGDocs());

  $("btnConflictCancel")?.addEventListener("click", () => {
    $("gdocsConflictModal").style.display = "none";
  });

  $("btnConflictOverwrite")?.addEventListener("click", async () => {
    $("gdocsConflictModal").style.display = "none";
    await actions.exportToGDocs(true);
  });
}

// ── Google Docs helpers ─────────────────────────────────────────────────────

async function _gdocsInit() {
  try {
    const { connected } = await API.getGDocsStatus();
    _setGDocsConnected(connected);
  } catch (_) {
    // endpoint may not exist yet — safe to ignore
  }
}

function _setGDocsConnected(connected) {
  const statusEl = $("gdocsConnectStatus");
  const connectBtn = $("btnConnectGDocs");
  const exportBtn = $("btnExportToGDocs");
  if (connected) {
    if (statusEl) statusEl.textContent = "✓ Google connected";
    if (connectBtn) connectBtn.style.display = "none";
    if (exportBtn) exportBtn.disabled = false;
  } else {
    if (statusEl) statusEl.textContent = "";
    if (connectBtn) connectBtn.style.display = "";
    if (exportBtn) exportBtn.disabled = true;
  }
}

function _gdocsPollConnection() {
  let tries = 0;
  const interval = setInterval(async () => {
    tries++;
    try {
      const { connected } = await API.getGDocsStatus();
      if (connected) {
        clearInterval(interval);
        _setGDocsConnected(true);
        toast("Google account connected!", "success");
      }
    } catch (_) {}
    if (tries >= 30) clearInterval(interval); // stop after ~60s
  }, 2000);
}

async function _refreshChapterDocLink() {
  if (!state.chapterId) return;
  try {
    const res = await API.getChapterDoc(state.chapterId);
    const wrap = $("chapterDocLinkWrap");
    const link = $("chapterDocLink");
    if (res?.doc_url) {
      link.href = res.doc_url;
      wrap.style.display = "block";
    } else {
      wrap.style.display = "none";
    }
  } catch (_) {
    $("chapterDocLinkWrap").style.display = "none";
  }
}

function _showConflictModal(detail) {
  $("gdocsConflictGdoc").textContent = detail.gdoc_excerpt ?? "(could not read Docs content)";
  $("gdocsConflictSpo").textContent = detail.spo_excerpt ?? "(could not read SPO draft)";
  const dateEl = $("gdocsConflictDate");
  if (detail.last_export_at) {
    const d = new Date(detail.last_export_at);
    dateEl.textContent = `Last exported: ${d.toLocaleString()}`;
  } else {
    dateEl.textContent = "";
  }
  $("gdocsConflictModal").style.display = "flex";
}

// Attached to actions so the conflict modal "Overwrite" button can call it with force=true
actions.exportToGDocs = async function exportToGDocs(force = false) {
  const subtopicId = state.activeSubtopicId;
  if (!subtopicId || !state.chapterId) {
    toast("Select a subtopic first.", "info");
    return;
  }

  const exportBtn = $("btnExportToGDocs");
  const originalLabel = exportBtn?.textContent ?? "📄 Export to Google Docs";
  if (exportBtn) { exportBtn.disabled = true; exportBtn.textContent = "⏳ Exporting…"; }

  try {
    const result = await API.exportToGDocs(state.chapterId, subtopicId, force);
    const linkHtml = `<a href="${result.doc_url}" target="_blank" rel="noopener"
      style="color:var(--accent); margin-left:4px;">Open Doc ↗</a>`;
    toast("Exported! " + linkHtml, "success", 7000);
    if (result.warning === "named_range_missing") {
      toast("⚠ Named range was lost — section re-appended to end of doc.", "info", 6000);
    }
    await _refreshChapterDocLink();
  } catch (err) {
    if (err.status === 409 || (err.message && err.message.includes("409"))) {
      let detail = {};
      try {
        // err.message format from api.js: "409: {...json...}"
        const jsonPart = err.message.replace(/^\d+:\s*/, "");
        detail = JSON.parse(jsonPart);
      } catch (_) {}
      _showConflictModal(detail);
    } else {
      toast(`Export failed: ${err.message}`, "error");
    }
  } finally {
    if (exportBtn) { exportBtn.disabled = false; exportBtn.textContent = originalLabel; }
  }
};

document.addEventListener("DOMContentLoaded", init);
