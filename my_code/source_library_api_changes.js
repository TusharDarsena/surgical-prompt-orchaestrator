// ── spo_frontend/static/js/source_library_api.js — 2 changes ─────────────────

// CHANGE 1 — add _tid() and _p() after the BASE line
// FIND:
const BASE = window.SPO_API_BASE || "http://localhost:8000";

// REPLACE WITH:
const BASE = window.SPO_API_BASE || "http://localhost:8000";

function _tid() { return localStorage.getItem("spo_active_thesis") || ""; }
function _p(path) {
  const id = _tid();
  if (!id) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}thesis_id=${encodeURIComponent(id)}`;
}


// CHANGE 2 — update all exports that hit thesis-scoped endpoints to use _p()
// FIND:
export const getLibraryView = () =>
  _get("/sources/library-view");

export const createGroup = (data) =>
  _post("/sources/groups", data);

export const updateGroup = (groupId, data) =>
  _patch(`/sources/groups/${groupId}`, data);

export const deleteGroup = (groupId) =>
  _delete(`/sources/groups/${groupId}`);

export const createSource = (groupId, data) =>
  _post(`/sources/groups/${groupId}/sources`, data);

export const updateSource = (groupId, sourceId, data) =>
  _patch(`/sources/groups/${groupId}/sources/${sourceId}`, data);

export const deleteSource = (groupId, sourceId) =>
  _delete(`/sources/groups/${groupId}/sources/${sourceId}`);

export const importSourceJson = (data) =>
  _post("/import/source", data);

// REPLACE WITH:
export const getLibraryView = () =>
  _get(_p("/sources/library-view"));

export const createGroup = (data) =>
  _post(_p("/sources/groups"), data);

export const updateGroup = (groupId, data) =>
  _patch(_p(`/sources/groups/${groupId}`), data);

export const deleteGroup = (groupId) =>
  _delete(_p(`/sources/groups/${groupId}`));

export const createSource = (groupId, data) =>
  _post(_p(`/sources/groups/${groupId}/sources`), data);

export const updateSource = (groupId, sourceId, data) =>
  _patch(_p(`/sources/groups/${groupId}/sources/${sourceId}`), data);

export const deleteSource = (groupId, sourceId) =>
  _delete(_p(`/sources/groups/${groupId}/sources/${sourceId}`));

export const importSourceJson = (data) =>
  _post(_p("/import/source"), data);
