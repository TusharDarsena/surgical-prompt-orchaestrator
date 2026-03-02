# Running SPO Backend Locally

## 1. Install

```bash
cd spo_backend
pip install -r requirements.txt
```

## 2. Run

```bash
uvicorn main:app --reload --port 8000
```

Open: **http://localhost:8000/docs**

That's it. Data saves to `~/spo_data/` automatically.

---

## 3. Test in Order (5-minute smoke test)

Open the Swagger UI at `/docs` and run these in sequence.

### Step 1 — Health check
```
GET /
```
Should return `"status": "running"` and your data_dir path.

### Step 2 — Create your thesis synopsis
```
POST /thesis/synopsis
```
Body:
```json
{
  "title": "Test Thesis",
  "author": "Your Name",
  "field": "Indian English Literature",
  "central_argument": "This thesis argues that...",
  "theoretical_framework": "Postcolonial feminism"
}
```

### Step 3 — Add a chapter
```
POST /thesis/chapters
```
Body:
```json
{
  "number": 1,
  "title": "Historical Background",
  "goal": "This chapter establishes the historical gap that the thesis fills."
}
```

### Step 4 — Add a subtopic
```
POST /thesis/chapters/chapter_01/subtopics
```
Body:
```json
{
  "number": "1.3.2",
  "title": "Entry of Feminism into Indian English Literature",
  "goal": "Establish the transition from male-authored nationalist texts to female-authored realist writing.",
  "position_in_argument": "This is the hinge point of the chapter argument."
}
```

### Step 5 — Add a source group (e.g. a thesis you're reading)
```
POST /sources/groups
```
Body:
```json
{
  "title": "Feminist Voices in Indian English Fiction",
  "author": "Sharma, R.",
  "year": 2003,
  "source_type": "thesis_chapter",
  "institution_or_publisher": "JNU",
  "description": "Primary source for Chapter 1 historical background."
}
```
**Copy the `group_id` from the response.**

### Step 6 — Paste your raw notes on this source (no structure needed yet)
```
POST /notes/source_group/{group_id}
```
Body:
```json
{
  "label": "Overall impressions",
  "content": "Sharma argues that pre-1947 male authors idealized women as nationalist symbols. Key chapters: 2 and 4. Chapter 2 has the best evidence for the representational gap argument. Watch out — only covers Bengali literature, not pan-Indian. Cites Chatterjee extensively."
}
```

### Step 7 — Add a source (one chapter PDF)
```
POST /sources/groups/{group_id}/sources
```
Body:
```json
{
  "label": "Sharma Ch.2",
  "title": "The Nationalist Imagination: Women in Pre-Independence Fiction",
  "chapter_or_section": "Chapter 2",
  "page_range": "45-89",
  "file_name": "sharma_2003_ch2.pdf"
}
```
**Copy the `source_id` from the response.**

### Step 8 — Paste raw notes on this specific chapter
```
POST /notes/source/{source_id}
```
Body:
```json
{
  "label": "Reading notes Ch.2",
  "content": "Pages 52-61 are the core. Main claim: female characters in Bankimchandra's work function as allegorical stand-ins for the nation, not as individuals. Sharma calls this 'nationalist idealization'. This term is useful — use it. p.67 has the quote about the 'mythologized feminine'. Limitations: only Bankimchandra and Tagore, doesn't cover minor writers."
}
```

### Step 9 — Now write the index card when ready
```
POST /sources/groups/{group_id}/sources/{source_id}/index-card
```
Body:
```json
{
  "key_claims": [
    "Pre-1947 male-authored texts constructed female characters as nationalist symbols, erasing individual agency (the 'nationalist idealization' thesis)",
    "Bankimchandra and Tagore are the primary examples; the pattern is consistent across both authors",
    "The gap between literary representation and lived experience of women is measurable and documented"
  ],
  "themes": ["nationalist_idealization", "pre_independence_literature", "representational_gap"],
  "time_period_covered": "1880-1947",
  "relevant_subtopics": ["1_3_2"],
  "limitations": "Covers only Bankimchandra and Tagore. Cannot support claims about pan-Indian or non-Bengali literary tradition.",
  "notable_authors_cited": ["Chatterjee, P.", "Bose, M."]
}
```

### Step 10 — Check suggested sources for your subtopic
```
GET /thesis/chapters/chapter_01/subtopics/1_3_2/suggested-sources
```
Should return the source you just indexed.

### Step 11 — Save a consistency chain entry (simulating post-writing)
```
POST /consistency/chapter_01/1_3_2
```
Body:
```json
{
  "subtopic_number": "1.3.2",
  "subtopic_title": "Entry of Feminism into Indian English Literature",
  "core_argument_made": "Established that pre-1947 male authors systematically constructed female characters as nationalist symbols using the concept of 'nationalist idealization' (Sharma Ch.2). This creates the historical baseline from which feminist writing departed.",
  "key_terms_established": ["nationalist idealization", "representational gap"],
  "sources_used": ["Sharma Ch.2"],
  "what_next_section_must_build_on": "Next section should use 'nationalist idealization' as the established baseline and show how post-independence feminist writers explicitly rejected this construction."
}
```

### Step 12 — Verify the chain works
```
GET /consistency/chapter_01/previous-for/1_3_3
```
*(Replace 1_3_3 with whatever your next subtopic ID is)*
Should return the summary you just saved.

---

## If something doesn't work

**`ModuleNotFoundError: No module named 'routers'`**
→ You're running uvicorn from the wrong directory.
→ `cd spo_backend` first, THEN `uvicorn main:app --reload`

**`ModuleNotFoundError: No module named 'fastapi'`**
→ Run `pip install -r requirements.txt` again
→ If using conda: `conda install fastapi uvicorn pydantic`

**Port already in use**
→ `uvicorn main:app --reload --port 8001`

**Data not saving / can't find files**
→ Check `GET /` — it shows your `data_dir`
→ Default is `~/spo_data/` — check that folder
