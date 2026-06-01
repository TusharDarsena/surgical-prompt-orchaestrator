/**
 * consistency_chain.js — Consistency Chain page
 *
 * Architecture:
 *   state  — single module-level state object
 *   render — pure render functions, read from state
 *   actions — async mutations (fetch + state update + render)
 *   init   — wire up DOM events, boot
 *
 * Thesis selector: reads spo_theses from localStorage (same pattern as write_section.js).
 *   Does NOT call /thesis/list — that is done by source_library.js which acts as cache refresher.
 * Chapter selector: listChapters() returns summaries (no subtopics). On chapter select, we call
 *   getChapter(id) to get the full chapter with subtopics embedded.
 * Chain: getChainForChapter(chapterId) returns { chain: [...] }.
 */

import * as API from "./api.js";

// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────

const state = {
  chapterSummaries: [],  // [{chapter_id, title, number}] — from listChapters()
  cachedChapter:    null, // full chapter with subtopics — from getChapter()
  currentChapterId: null,
  chain:            [],  // from getChainForChapter()
};

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

function _esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function _activeThesisId() {
  return localStorage.getItem("spo_active_thesis") || "";
}

function _loadThesesIndex() {
  try { return JSON.parse(localStorage.getItem("spo_theses") || "[]"); } catch { return []; }
}

function toast(msg, type = "info", duration = 3500) {
  const container = $("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ─────────────────────────────────────────────────────────────────────────────
// RENDER
// ─────────────────────────────────────────────────────────────────────────────

function renderThesisSelector() {
  const sel = $("ccThesisSelect");
  if (!sel) return;
  const theses = _loadThesesIndex();
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

function renderChapterSelector() {
  const sel = $("chapterSelect");
  sel.innerHTML = "";

  if (!state.chapterSummaries.length) {
    sel.innerHTML = `<option value="">— No chapters —</option>`;
    return;
  }
  for (const ch of state.chapterSummaries) {
    const opt = document.createElement("option");
    opt.value = ch.chapter_id;
    opt.textContent = `Ch.${ch.number} — ${ch.title}`;
    if (ch.chapter_id === state.currentChapterId) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderMetrics() {
  const subtopics = state.cachedChapter?.subtopics ?? [];
  const total = subtopics.length;
  const done  = state.chain.length;
  const pct   = total ? Math.round(done / total * 100) : 0;

  $("metricSubtopics").textContent = total;
  $("metricComplete").textContent  = done;
  $("metricProgress").textContent  = `${pct}%`;
  $("progressFill").style.width    = `${pct}%`;
}

function resetMetrics() {
  $("metricSubtopics").textContent = "—";
  $("metricComplete").textContent  = "—";
  $("metricProgress").textContent  = "—";
  $("progressFill").style.width    = "0%";
}

function renderThread() {
  const container = $("threadContainer");
  const subtopics  = state.cachedChapter?.subtopics ?? [];
  const chapterId  = state.currentChapterId;

  if (!subtopics.length) {
    container.innerHTML = `<div class="cc-empty-state">No subtopics defined in this chapter.</div>`;
    hideExport();
    return;
  }

  // Build lookup: subtopic_id → chain entry
  const completedMap = new Map(state.chain.map(s => [s.subtopic_id, s]));

  container.innerHTML = "";
  for (const sub of subtopics) {
    container.appendChild(
      _buildThreadBlock(sub, completedMap.get(sub.subtopic_id) ?? null, chapterId)
    );
  }

  if (state.chain.length) {
    renderExport();
  } else {
    hideExport();
  }
}

function _buildThreadBlock(sub, summary, chapterId) {
  const isDone = summary !== null;
  const block  = document.createElement("div");
  block.className = `thread-block ${isDone ? "thread-done" : "thread-pending"}`;
  block.id = `block-${sub.subtopic_id}`;

  let bodyHtml = `<div class="thread-goal">${_esc(sub.goal ?? "")}</div>`;

  if (isDone) {
    const termsHtml = summary.key_terms_established?.length
      ? summary.key_terms_established.map(t => `<code class="term">${_esc(t)}</code>`).join(" ")
      : null;
    const sourcesText = summary.sources_used?.length
      ? summary.sources_used.join(", ")
      : null;
    const bridge = summary.what_next_section_must_build_on ?? null;

    bodyHtml += `
      <div class="thread-argument-label">What was argued:</div>
      <div class="thread-argument">${_esc(summary.core_argument_made)}</div>
    `;
    if (termsHtml) {
      bodyHtml += `<div class="thread-terms"><span class="thread-meta-label">Terms established:</span> ${termsHtml}</div>`;
    }
    if (sourcesText) {
      bodyHtml += `<div class="thread-sources"><span class="thread-meta-label">Sources used:</span> ${_esc(sourcesText)}</div>`;
    }
    if (bridge) {
      bodyHtml += `<div class="thread-bridge"><span class="thread-meta-label">➡ Bridge to next:</span> ${_esc(bridge)}</div>`;
    }
    bodyHtml += `
      <div class="thread-actions">
        <button class="btn btn-ghost btn-delete-summary"
          data-chapter="${_esc(chapterId)}"
          data-subtopic="${_esc(sub.subtopic_id)}"
          type="button"
          style="font-size:11px;padding:4px 10px;">
          🗑️ Delete Summary
        </button>
      </div>
    `;
  } else {
    bodyHtml += `
      <div class="thread-pending-caption">
        ⬜ Pending — Not yet written.
        Go to <strong>Write a Section</strong> to complete this subtopic.
      </div>
    `;
  }

  block.innerHTML = `
    <div class="thread-header">
      <div class="thread-title">
        <span class="thread-icon">${isDone ? "✅" : "⬜"}</span>
        <span class="thread-num">${_esc(sub.number)}</span>
        <span class="thread-name">${_esc(sub.title)}</span>
      </div>
      <span class="thread-status ${isDone ? "thread-status-done" : "thread-status-pending"}">
        ${isDone ? "Complete" : "Pending"}
      </span>
    </div>
    <div class="thread-body">${bodyHtml}</div>
  `;
  return block;
}

function renderExport() {
  const chapter = state.cachedChapter;
  const lines   = [`# Argument Thread — ${chapter?.title ?? state.currentChapterId}\n`];

  for (const s of state.chain) {
    lines.push(`## ${s.subtopic_number ?? ""} — ${s.subtopic_title ?? ""}`);
    if (s.core_argument_made) lines.push(s.core_argument_made);
    if (s.key_terms_established?.length) {
      lines.push(`Terms: ${s.key_terms_established.join(", ")}`);
    }
    if (s.what_next_section_must_build_on) {
      lines.push(`Bridge: ${s.what_next_section_must_build_on}`);
    }
    lines.push("");
  }

  const text = lines.join("\n");
  $("threadExport").value = text;
  $("exportSection").style.display = "block";

  $("copyButton").onclick = () => {
    navigator.clipboard.writeText(text)
      .then(() => toast("Thread copied!", "success"))
      .catch(() => toast("Copy failed — select and copy manually.", "error"));
  };
}

function hideExport() {
  $("exportSection").style.display = "none";
  $("threadExport").value = "";
}

// ─────────────────────────────────────────────────────────────────────────────
// ACTIONS
// ─────────────────────────────────────────────────────────────────────────────

const actions = {

  async onThesisChange(id) {
    localStorage.setItem("spo_active_thesis", id);
    state.chapterSummaries = [];
    state.cachedChapter    = null;
    state.currentChapterId = null;
    state.chain            = [];
    await actions.loadChapters();
  },

  async loadChapters() {
    $("chapterSelect").innerHTML = `<option value="">Loading…</option>`;
    resetMetrics();
    $("threadContainer").innerHTML = `<div class="cc-empty-state">Loading chapters…</div>`;
    hideExport();

    try {
      const chapters = await API.listChapters();
      state.chapterSummaries = chapters ?? [];
      renderChapterSelector();

      if (!state.chapterSummaries.length) {
        $("threadContainer").innerHTML = `<div class="cc-empty-state">No chapters yet. Set up your thesis first.</div>`;
        return;
      }

      // Auto-select first chapter
      const firstId = state.chapterSummaries[0].chapter_id;
      state.currentChapterId = firstId;
      renderChapterSelector();
      await actions.loadChain(firstId);
    } catch (err) {
      $("chapterSelect").innerHTML = `<option value="">— Error —</option>`;
      $("threadContainer").innerHTML = `<div class="cc-empty-state cc-error">Failed to load chapters: ${_esc(err.message)}</div>`;
      toast(`Failed to load chapters: ${err.message}`, "error");
    }
  },

  async loadChain(chapterId) {
    if (!chapterId) return;
    state.currentChapterId = chapterId;

    $("threadContainer").innerHTML = `<div class="cc-empty-state">Loading argument thread…</div>`;
    resetMetrics();
    hideExport();

    try {
      // Fetch full chapter (has subtopics) and chain in parallel
      const [fullChapter, chainRes] = await Promise.all([
        API.getChapter(chapterId),
        API.getChainForChapter(chapterId),
      ]);

      state.cachedChapter = fullChapter;
      state.chain         = chainRes?.chain ?? [];

      renderMetrics();
      renderThread();
    } catch (err) {
      $("threadContainer").innerHTML = `<div class="cc-empty-state cc-error">Failed to load thread: ${_esc(err.message)}</div>`;
      toast(`Error loading chain: ${err.message}`, "error");
    }
  },

  async deleteSummary(chapterId, subtopicId) {
    if (!confirm("Delete this consistency summary? The subtopic will revert to Pending.")) return;
    try {
      await API.deleteConsistencySummary(chapterId, subtopicId);
      toast("Summary deleted", "success");
      await actions.loadChain(chapterId);
    } catch (err) {
      toast(`Delete failed: ${err.message}`, "error");
    }
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  renderThesisSelector();

  $("ccThesisSelect").addEventListener("change", e => actions.onThesisChange(e.target.value));

  $("chapterSelect").addEventListener("change", e => {
    if (e.target.value) actions.loadChain(e.target.value);
  });

  // Event delegation — delete buttons are rendered dynamically inside #threadContainer
  $("threadContainer").addEventListener("click", e => {
    const btn = e.target.closest(".btn-delete-summary");
    if (!btn) return;
    actions.deleteSummary(btn.dataset.chapter, btn.dataset.subtopic);
  });

  // React if thesis is changed on another tab/page
  window.addEventListener("storage", e => {
    if (e.key === "spo_active_thesis" || e.key === "spo_theses") {
      renderThesisSelector();
      actions.loadChapters();
    }
  });

  await actions.loadChapters();
}

document.addEventListener("DOMContentLoaded", init);
