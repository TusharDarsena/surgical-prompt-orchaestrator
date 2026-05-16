

The key insight is: SPO is already using `notebooklm-py` (it's in `requirements.txt` and there's a `notebooklm_service.py`). The current pain points in the workflow are:

1. **Prompt generation is automated but delivery is manual** — user still has to copy-paste into NotebookLM
2. **The consistency summary generation** (Card 04) says "Run via NotebookLM" — still manual
3. **Source onboarding** requires NotebookLM to extract index card JSON — still manual
4. **Cross-source synthesis** is absent — no tool queries across all notebooks to find argumentative gaps
5. **The Stage 2 Gemini elaboration** is manual


---

**Feature 1: Automate the Writing Prompt Delivery (notebooklm-py)**

Right now, Card 02 ("Generate Drafts") shows a run table where you click a row and presumably copy-paste the prompt into NotebookLM manually. The `notebooklm_service.py` already exists and `notebooklm-py` is in requirements — this means the plumbing is partially there but likely incomplete.

What to finish: `notebooklm_service.py` should call `notebooklm-py`'s `NotebookLMClient` to submit the compiled writing prompt directly to the right notebook (the one containing sources for that subtopic), get the response back, and populate the draft textarea automatically. The "open via ↗" button in the run table UI should become a "Run in NLM" button that fires the API call and streams the draft back.

This is the single highest-ROI feature — it eliminates the most friction-heavy manual step in the core loop.

**Feature 2: Auto-generate the Consistency Summary (notebooklm-py)**

Card 04's button currently says "Generate Summary via NotebookLM" but by the UI comment "Run via NotebookLM — generates a consistency summary and saves it to your summary doc" — this is still manual. Wire it up: after the draft is saved in Card 03, hitting Card 04's button should send the draft text to `notebooklm-py` with a fixed summarization prompt ("Summarize: what was the central argument made, what key terms were introduced, and what must the next section build on?") and auto-populate the `SectionSummary` fields in the consistency model. The writer reviews and confirms before saving. This tightens the feedback loop from ~5 minutes of manual work to a single click.

**Feature 3: Automated Source Indexing Pipeline (notebooklm-py + notebooklm-mcp-cli)**

Currently, source onboarding is a multi-step manual process: upload PDFs to NotebookLM, paste the `generate_source_json.txt` prompt, copy the JSON back, paste it into SPO. The `notebooklm-py` library can handle this entirely programmatically:

- SPO detects a new source folder in the scan (already has the scan infrastructure in `drive.py`)
- Creates a temporary NotebookLM notebook via `notebooklm-py`, uploads the PDFs from the Drive links
- Fires the `generate_source_json.txt` prompt against it
- Retrieves the response, calls the existing `do_auto_import()` in `source_importer.py`
- Deletes the temp notebook

This turns what is probably a 15-minute manual process per source into a background job triggered from the Source Library UI. Given you likely have dozens of sources, this is transformative.

**Feature 4: Cross-Notebook Argumentative Gap Scanner (notebooklm-mcp-cli)**

This is the creative one. Right now SPO is excellent at forward-chaining within a subtopic sequence but has no mechanism to ask "across all my sources, what counterarguments am I not addressing?" or "which chapters of my own sources are underused in my chapterization?"

Use `notebooklm-mcp-cli`'s `cross_notebook_query` against all per-thesis notebooks with a prompt like: "Given this thesis's central argument [inject from thesis JSON], which of these source chapters presents the strongest counterargument I have not yet assigned to any subtopic?" — pipe the answer into a new UI card in the Thesis Setup page as a "Blind Spot Audit." This is something neither Claude nor NotebookLM can do individually because it requires querying across the actual PDFs simultaneously; `cross_notebook_query` makes it possible.

**Feature 5: Source Fulltext Retrieval for Index Card Drafting (notebooklm-py)**

The README explicitly says "Index cards are human-written because AI generates hallucinated or irrelevant claims." That's true for unsupervised generation — but `notebooklm-py` exposes source fulltext retrieval, which means you can pull the actual indexed text of a specific chapter, show it inline in the Source Library UI alongside the index card editor, and let the writer make claims with the actual text visible. This isn't AI generating the card — it's giving the human better material to work from. Much faster than having to open the PDF separately.

---
