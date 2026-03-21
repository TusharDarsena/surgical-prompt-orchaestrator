// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ADDITIONS TO: spo_frontend/static/js/source_library_api.js
// INSERT LOCATION: at the end of the file, after the existing exports
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// ── Index Card Generation ─────────────────────────────────────────────────────

export const generateIndexCards = (scanKeys) =>
  _post("/notebooklm/generate-index-cards", { scan_keys: scanKeys });

// thesis_name passed as query param (not path) — handles spaces + special chars safely
export const getIndexCardState = (thesisName) =>
  _get(`/notebooklm/index-card-state?thesis_name=${encodeURIComponent(thesisName)}`);

export const getIndexCardBatchState = (batchId) =>
  _get(`/notebooklm/index-card-batch-state/${batchId}`);
