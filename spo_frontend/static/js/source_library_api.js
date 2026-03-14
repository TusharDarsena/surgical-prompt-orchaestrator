/**
 * source_library_api.js
 * All API calls for the Source Library page.
 * Mirrors the endpoints in spo_backend/routers/sources.py, drive.py, importer.py
 */

const BASE = window.SPO_API_BASE || "http://localhost:8000";

async function _req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

const _get    = p       => _req("GET",    p);
const _post   = (p, b)  => _req("POST",   p, b);
const _patch  = (p, b)  => _req("PATCH",  p, b);
const _delete = p       => _req("DELETE", p);

// ── Library bulk view ─────────────────────────────────────────────────────────
export const getLibraryView = () =>
  _get("/sources/library-view");

// ── Source Groups ─────────────────────────────────────────────────────────────
export const createGroup = (data) =>
  _post("/sources/groups", data);

export const updateGroup = (groupId, data) =>
  _patch(`/sources/groups/${groupId}`, data);

export const deleteGroup = (groupId) =>
  _delete(`/sources/groups/${groupId}`);

// ── Sources ───────────────────────────────────────────────────────────────────
export const createSource = (groupId, data) =>
  _post(`/sources/groups/${groupId}/sources`, data);

export const updateSource = (groupId, sourceId, data) =>
  _patch(`/sources/groups/${groupId}/sources/${sourceId}`, data);

export const deleteSource = (groupId, sourceId) =>
  _delete(`/sources/groups/${groupId}/sources/${sourceId}`);

// ── Import ────────────────────────────────────────────────────────────────────
export const importSourceJson = (data) =>
  _post("/import/source", data);

// ── Drive / Scan ──────────────────────────────────────────────────────────────
export const scanLocalFolder = (rootPath) =>
  _post("/drive/scan-local", { root_path: rootPath });

export const getLocalFiles = () =>
  _get("/drive/local-files");

export const registerDriveLinks = (driveFolderId) =>
  _post("/drive/register-links", { drive_folder_id: driveFolderId });

export const copyDriveLinks = (thesisName) =>
  _get(`/drive/links/${thesisName}`);
