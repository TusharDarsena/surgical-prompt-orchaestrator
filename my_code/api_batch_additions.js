// ── ADD these two functions at the end of the NotebookLM Automation section in api.js ──
// Place after the existing nlmDeleteNotebook export (~line 73)

export const nlmRunBatch = (chapterId, subtopicIds, wordCount, styleNotes) => {
  const body = { subtopic_ids: subtopicIds };
  if (wordCount)  body.word_count           = wordCount;
  if (styleNotes) body.academic_style_notes = styleNotes;
  return _post(`/notebooklm/run-batch/${chapterId}`, body);
};

export const nlmBatchState = (batchId) =>
  _get(`/notebooklm/batch-state/${batchId}`);
