/**
 * api.js — fetch wrappers for the SPO backend.
 *
 * Every function returns the parsed JSON body on success, or throws an
 * Error with a human-readable message on HTTP / network failure.
 * Callers never touch fetch() directly.
 */

const BASE = window.SPO_API_BASE || "http://localhost:8000";

async function _request(method, path, body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== null) opts.body = JSON.stringify(body);

  const res = await fetch(`${BASE}${path}`, opts);

  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch (_) {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

const _get    = (path)        => _request("GET",    path);
const _post   = (path, body)  => _request("POST",   path, body);
const _delete = (path)        => _request("DELETE", path);

function _tid() { return localStorage.getItem("spo_active_thesis") || ""; }
function _p(path) {
  const id = _tid();
  if (!id) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}thesis_id=${encodeURIComponent(id)}`;
}

// ── Chapters ──────────────────────────────────────────────────────────────────

export const listChapters = () =>
  _get(_p("/thesis/chapters"));

// ── Compiler ──────────────────────────────────────────────────────────────────

export const compilePrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const tid = _tid();
  if (tid) params.set("thesis_id", tid);
  const qs = params.toString() ? `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};

// ── Section Drafts ────────────────────────────────────────────────────────────

export const getDraft = (chapterId, subtopicId) =>
  _get(_p(`/sections/${chapterId}/${subtopicId}/draft`));

export const saveDraft = (chapterId, subtopicId, text) =>
  _post(_p(`/sections/${chapterId}/${subtopicId}/draft`), { text });

export const deleteDraft = (chapterId, subtopicId) =>
  _delete(_p(`/sections/${chapterId}/${subtopicId}/draft`));

// ── NotebookLM Automation ─────────────────────────────────────────────────────

export const nlmStatus = () =>
  _get("/notebooklm/status");

export const getPreviousSummary = (chapterId, subtopicId) =>
  _get(_p(`/consistency/${chapterId}/previous-for/${subtopicId}`));

export const nlmRun = (chapterId, subtopicId, wordCount, styleNotes) => {
  const body = {};
  if (wordCount)  body.word_count              = wordCount;
  if (styleNotes) body.academic_style_notes     = styleNotes;
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

export const nlmBatchState = (batchId) =>
  _get(`/notebooklm/batch-state/${batchId}`);

// ── Consistency ───────────────────────────────────────────────────────────────

export const getChainForChapter = (chapterId) =>
  _get(_p(`/consistency/${chapterId}`));

export const saveConsistencySummary = (chapterId, subtopicId, data) =>
  _post(_p(`/consistency/${chapterId}/${subtopicId}`), data);

export const generateConsistencyPrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  // Re-uses the compiler endpoint — consistency summary is Stage 1 driven the same way.
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const qs = params.toString() ? `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};
