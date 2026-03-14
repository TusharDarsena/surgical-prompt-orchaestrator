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

// ── Chapters ──────────────────────────────────────────────────────────────────

export const listChapters = () =>
  _get("/thesis/chapters");

// ── Compiler ──────────────────────────────────────────────────────────────────

export const compilePrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const qs = params.toString() ? `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};

// ── Section Drafts ────────────────────────────────────────────────────────────

export const getDraft = (chapterId, subtopicId) =>
  _get(`/sections/${chapterId}/${subtopicId}/draft`);

export const saveDraft = (chapterId, subtopicId, text) =>
  _post(`/sections/${chapterId}/${subtopicId}/draft`, { text });

export const deleteDraft = (chapterId, subtopicId) =>
  _delete(`/sections/${chapterId}/${subtopicId}/draft`);

// ── NotebookLM Automation ─────────────────────────────────────────────────────

export const nlmStatus = () =>
  _get("/notebooklm/status");

export const getPreviousSummary = (chapterId, subtopicId) =>
  _get(`/consistency/${chapterId}/previous-for/${subtopicId}`);

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

// ── Consistency ───────────────────────────────────────────────────────────────

export const getChainForChapter = (chapterId) =>
  _get(`/consistency/${chapterId}`);

export const saveConsistencySummary = (chapterId, subtopicId, data) =>
  _post(`/consistency/${chapterId}/${subtopicId}`, data);

export const generateConsistencyPrompt = (chapterId, subtopicId, wordCount, styleNotes) => {
  // Re-uses the compiler endpoint — consistency summary is Stage 1 driven the same way.
  const params = new URLSearchParams();
  if (wordCount)  params.set("word_count", wordCount);
  if (styleNotes) params.set("academic_style_notes", styleNotes);
  const qs = params.toString() ? `?${params}` : "";
  return _get(`/compile/notebooklm-prompt/${chapterId}/${subtopicId}${qs}`);
};
