/**
 * write_section.js — BATCH CHANGES
 * ==================================
 * This file lists every change needed. All other code is untouched.
 *
 * CHANGE 1 — Add batchId to state object
 * CHANGE 2 — Replace runAllIdle() with batch version
 * CHANGE 3 — Update poller to use batch state when a batch is active
 * CHANGE 4 — Update selectChapter to clear batchId on chapter switch
 */


// ─────────────────────────────────────────────────────────────────────────────
// CHANGE 1 — state object
// Find the existing state object and add one field after `chain: []`
//
//   chain:       [],
//
// Add directly below it:
// ─────────────────────────────────────────────────────────────────────────────

  // active batch ID — set when runAllIdle fires, cleared when batch completes
  batchId: null,


// ─────────────────────────────────────────────────────────────────────────────
// CHANGE 2 — actions.runAllIdle()
// Replace the ENTIRE existing runAllIdle() method with this:
// ─────────────────────────────────────────────────────────────────────────────

  async runAllIdle() {
    const idle = state.subtopics.filter(
      s => getRunState(s.subtopic_id).status === "idle"
    );
    if (!idle.length) { toast("No idle subtopics", "info"); return; }

    const idleIds = idle.map(s => s.subtopic_id);

    try {
      const res = await API.nlmRunBatch(
        state.chapterId,
        idleIds,
        state.wordCount  || null,
        state.styleNotes || null,
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


// ─────────────────────────────────────────────────────────────────────────────
// CHANGE 3 — poller._tick()
// Replace the ENTIRE existing _tick() method with this:
// ─────────────────────────────────────────────────────────────────────────────

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
          status:           snap.status,
          error:            snap.error,
          sources_uploaded: snap.sources_uploaded,
          sources_failed:   snap.sources_failed,
          batch_id:         state.batchId,
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
        const rs   = await API.nlmState(state.chapterId, s.subtopic_id);
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


// ─────────────────────────────────────────────────────────────────────────────
// CHANGE 4 — actions.selectChapter()
// Find these two lines inside selectChapter (around line 331):
//
//   state.runStates        = {};
//   state.drafts           = {};
//
// Add one line directly below them:
// ─────────────────────────────────────────────────────────────────────────────

    state.batchId          = null;   // ← ADD: clear any in-flight batch on chapter switch
