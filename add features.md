
**Feature 2: Auto-generate the Consistency Summary (notebooklm-py)**

Card 04's button currently says "Generate Summary via NotebookLM" but by the UI comment "Run via NotebookLM — generates a consistency summary and saves it to your summary doc" — this is still manual. Wire it up: after the draft is saved in Card 03, hitting Card 04's button should send the draft text to `notebooklm-py` with a fixed summarization prompt ("Summarize: what was the central argument made, what key terms were introduced, and what must the next section build on?") and auto-populate the `SectionSummary` fields in the consistency model. The writer reviews and confirms before saving. This tightens the feedback loop from ~5 minutes of manual work to a single click.

**Feature 3: Automated Source Indexing Pipeline (done)**

**Feature 4: Cross-Notebook Argumentative Gap Scanner (notebooklm-mcp-cli)**

This is the creative one. Right now SPO is excellent at forward-chaining within a subtopic sequence but has no mechanism to ask "across all my sources, what counterarguments am I not addressing?" or "which chapters of my own sources are underused in my chapterization?"

Use `notebooklm-mcp-cli`'s `cross_notebook_query` against all per-thesis notebooks with a prompt like: "Given this thesis's central argument [inject from thesis JSON], which of these source chapters presents the strongest counterargument I have not yet assigned to any subtopic?" — pipe the answer into a new UI card in the Thesis Setup page as a "Blind Spot Audit." This is something neither Claude nor NotebookLM can do individually because it requires querying across the actual PDFs simultaneously; `cross_notebook_query` makes it possible.

---


Here is the comprehensive breakdown of the consistency chain fragility, why forcing structural schemas onto an LLM creates technical debt, and the exact path to implement the "Rolling Holographic Source."

---

## The Core Problem: Forced JSON Schemas for Argumentative Continuity

Currently, the SPO maintains argumentative flow between subtopics by forcing NotebookLM to summarize its own work. The `suggest_summary_service` prompts the LLM to output a rigid JSON object containing exactly three keys (`core_argument_made`, `key_terms_established`, `what_next_section_must_build_on`).

This creates a massive architectural bottleneck:

1. **Schema Hallucinations:** You are forcing a conversational LLM to act like a deterministic REST API. If NotebookLM outputs `"key_terms"` instead of `"key_terms_established"`, or wraps the output in markdown fences, `json.loads` throws an exception and the orchestration loop crashes.
2. **Lossy Compression:** Summarizing an intricate, beautifully written academic section into three sterile sentences strips away tone, cadence, and nuance. The next section starts "cold" because it only sees a sterile summary, not the actual writing style.
3. **The Sequencing Trap:** Because these summaries are saved to disk in a rigid chronological chain, reordering your thesis (e.g., moving Section 1.3 to Chapter 4) instantly invalidates the entire chain.

---

## The Ultimate Fix: The "Rolling Holographic Source"

You built this on NotebookLM to utilize its massive, native context window. Instead of wrestling with regex (like your `Fix 9` trailing comma stripper) to parse brittle JSON summaries, you must let the RAG engine do what it does best: read raw text.

**The Solution:** Stop summarizing. Before generating a new section, concatenate every previously written section into a single, raw Markdown string. Upload this directly to the notebook as a temporary text source.

### The Exact Implementation Guide

**1. Gut the Legacy Code (Massive Deletion)**

* **Delete** `routers/consistency.py` entirely.
* **Delete** `suggest_summary_service` from `services/notebooklm_service.py`.
* **Delete** the regex cleaning functions (`_clean_nlm_json`).
* **Delete** the `consistency_chain` local directory logic from `storage.py`.

**2. Implement the Dynamic Compiler (In `compiler_service.py`)**

* When `_run_sequence` initiates for a subtopic, query your AST/Outline array to identify all subtopics that logically precede the current one.
* Concatenate their `draft_text` into a single string: `compiled_draft_text`.

**3. The Native Upload (In `notebooklm_service.py`)**

* Right before sending `prompt_1`, use the existing `add_text` method to upload this string as a temporary source:
```python
draft_source = await client.sources.add_text(
    notebook_id,
    title="00_Current_Thesis_Draft",
    content=compiled_draft_text,
    wait=True
)

```



**4. Update the Master Prompt**

* Remove all the complex f-string logic in `_render_notebooklm_prompt` that tries to inject the previous section's `key_terms`.
* Replace it with a single, static directive:
> *"Source '00_Current_Thesis_Draft' is the current compiled draft of the thesis. Read it to absorb the tone, pacing, and established vocabulary. Using the external PDF sources provided, write the next logical section. Do not re-explain concepts or re-define terms already established in the draft."*



**5. Clean Up**

* In the `finally` block of `_run_sequence`, ensure `00_Current_Thesis_Draft` is deleted via `client.sources.delete()`, keeping the notebook clean for the next run.

---

## The Architectural Benefits

By shifting the context burden away from rigid JSON schemas and back onto NotebookLM’s native RAG engine, the system becomes significantly more robust:

* **Eradication of Parse Errors:** Because you no longer force the LLM to output machine-readable JSON, `JSONDecodeError` and `ValueError` exceptions are physically impossible in this part of the loop.
* **Auto-Healing Sequencing:** If you completely restructure the thesis outline, the orchestrator doesn't care. It simply concatenates the *new* order into `00_Current_Thesis_Draft` on the fly. The context is always 100% accurate with zero recalculation required.
* **Perfect Tonal Cohesion:** NotebookLM reads the *actual text* it previously generated. It will naturally mimic the specific academic tone, vocabulary, and paragraph pacing you’ve already established, resulting in a draft that requires far less manual editing in Google Docs.
