"""
import_fixer.py — Schema Repair Helpers for SPO Import Tabs
────────────────────────────────────────────────────────────
Drop this file into your project root (next to api.py / ui.py).

Provides two render functions you call inside your import tabs:

    render_chapter_import_tab(chapter_id)
    render_source_import_tab()

Each one:
  1. Accepts the uploaded JSON (tolerates the formats you actually have)
  2. Detects missing/mismatched fields
  3. Shows inline fill-in forms for anything missing
  4. Posts clean data to the API only when everything is present

────────────────────────────────────────────────────────────
Usage — replace the body of your import tabs:

  # In whatever page handles chapter import:
  from import_fixer import render_chapter_import_tab
  render_chapter_import_tab(chapter_id)

  # In 2_Source_Library.py, replace the `with tab_import:` block body:
  from import_fixer import render_source_import_tab
  render_source_import_tab()
"""

import json
import re
import streamlit as st
import api


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL — JSON cleaning & normalization
# ══════════════════════════════════════════════════════════════════════════════

def _clean_raw_text(raw: str) -> str:
    """
    Strip 'response N' prefixes that NotebookLM sometimes outputs before JSON.
    Also strips trailing/leading whitespace.
    """
    cleaned = re.sub(r"(?im)^response\s+\d+\s*\n?", "", raw)
    return cleaned.strip()


def _parse_json_tolerant(raw: str):
    """
    Try to parse JSON. If multiple JSON objects exist (NotebookLM multi-response),
    collect all of them. Returns (list_of_dicts, error_string_or_None).
    """
    cleaned = _clean_raw_text(raw)
    objects = []
    errors = []

    # Try the whole thing first
    try:
        obj = json.loads(cleaned)
        return [obj], None
    except json.JSONDecodeError:
        pass

    # Find all top-level {...} blocks
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = cleaned[start:i + 1]
                try:
                    objects.append(json.loads(chunk))
                except json.JSONDecodeError as e:
                    errors.append(str(e))
                start = None

    if objects:
        return objects, None
    return [], f"Could not parse any valid JSON. Errors: {'; '.join(errors)}"


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL — Chapter schema normalization
# ══════════════════════════════════════════════════════════════════════════════

def _flatten_chapter_json(data: dict) -> dict:
    """
    Converts your chapters.json flat format:
        {"Chapter 1: Introduction": {"1.1": "...", "1.2": {"title": ..., "subtopics": {...}}}}

    Into the SPO chapterization schema:
        {number, title, goal, chapter_arc, subtopics: [{number, title, goal, position_in_argument}]}

    goal and chapter_arc will be empty strings — the user fills them in the UI.
    """
    # Already in correct schema?
    if "subtopics" in data and isinstance(data.get("subtopics"), list):
        return data

    # Flat chapter map — find the chapter key
    chapter_key = None
    chapter_body = None
    for k, v in data.items():
        if re.match(r"Chapter\s+\d+", k, re.IGNORECASE) or isinstance(v, dict):
            chapter_key = k
            chapter_body = v
            break

    if not chapter_key or not isinstance(chapter_body, dict):
        return data  # can't normalize, return as-is

    num_match = re.search(r"\d+", chapter_key)
    chapter_num = int(num_match.group()) if num_match else 1
    chapter_title = re.sub(r"^Chapter\s+\d+\s*:\s*", "", chapter_key, flags=re.IGNORECASE).strip()

    subtopics = []

    def recurse(obj, parent=""):
        for k, v in obj.items():
            if re.match(r"Chapter", k, re.IGNORECASE):
                continue
            if isinstance(v, str):
                subtopics.append({
                    "number": k,
                    "title": v,
                    "goal": "",
                    "position_in_argument": "",
                })
            elif isinstance(v, dict):
                title = v.get("title", k)
                subtopics.append({
                    "number": k,
                    "title": title,
                    "goal": "",
                    "position_in_argument": "",
                })
                if "subtopics" in v and isinstance(v["subtopics"], dict):
                    recurse(v["subtopics"])

    recurse(chapter_body)

    return {
        "number": chapter_num,
        "title": chapter_title,
        "goal": "",
        "chapter_arc": "",
        "subtopics": subtopics,
    }


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL — Source/index_cards normalization
# ══════════════════════════════════════════════════════════════════════════════

def _merge_source_responses(objects: list) -> dict:
    """
    When NotebookLM outputs multiple 'response N' JSON blocks for the same work,
    merge their chapters lists into one source object.
    Deduplicates chapters by label+title.
    """
    if not objects:
        return {}
    if len(objects) == 1:
        return objects[0]

    # Use first object as base for metadata
    merged = dict(objects[0])
    seen = set()
    all_chapters = []

    for obj in objects:
        for ch in obj.get("chapters", []):
            key = (ch.get("label", ""), ch.get("title", ""))
            if key not in seen:
                seen.add(key)
                all_chapters.append(ch)

    merged["chapters"] = all_chapters
    return merged


def _normalize_chapter_entry(ch: dict) -> dict:
    """Mirrors the backend's _normalize_source_chapter for frontend preview."""
    c = dict(ch)
    for alt in ("file", "filename", "pdf", "pdf_name"):
        if alt in c and "file_name" not in c:
            c["file_name"] = c.pop(alt)
            break
    for alt in ("chapter_title", "name", "section_title"):
        if alt in c and "title" not in c:
            c["title"] = c.pop(alt)
            break
    if not c.get("label"):
        fname = c.get("file_name", "")
        title = c.get("title", "")
        c["label"] = fname.replace(".pdf", "").replace("_", " ").title()[:30] if fname else title[:30] or "Unlabelled"
    for alt in ("time_period", "period", "historical_period"):
        if alt in c and "time_period_covered" not in c:
            c["time_period_covered"] = c.pop(alt)
            break
    for alt in ("citations", "cited_authors", "authors_cited", "scholars"):
        if alt in c and "notable_authors_cited" not in c:
            c["notable_authors_cited"] = c.pop(alt)
            break
    for alt in ("claims", "main_claims", "arguments"):
        if alt in c and "key_claims" not in c:
            c["key_claims"] = c.pop(alt)
            break
    for alt in ("theme", "tags", "keywords"):
        if alt in c and "themes" not in c:
            c["themes"] = c.pop(alt)
            break
    for alt in ("limitation", "constraints", "cannot_support"):
        if alt in c and "limitations" not in c:
            c["limitations"] = c.pop(alt)
            break
    if isinstance(c.get("limitations"), list):
        c["limitations"] = " ".join(c["limitations"])
    return c


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — render_chapter_import_tab
# ══════════════════════════════════════════════════════════════════════════════

def render_chapter_import_tab(chapter_id: str):
    """
    Call this inside your chapter import tab.
    Handles both the correct chapterization.json schema AND the flat chapters.json format.

    Args:
        chapter_id: e.g. "chapter_01" — passed to POST /import/chapterization/{chapter_id}
    """
    st.caption(
        "Accepts the standard `chapterization.json` **or** your flat `chapters.json` format. "
        "Missing fields (`goal`, `chapter_arc`, subtopic goals) can be filled in below."
    )

    uploaded = st.file_uploader(
        "Upload chapter JSON", type="json", key=f"ch_upload_{chapter_id}"
    )

    if not uploaded:
        return

    raw = uploaded.read().decode("utf-8")
    objects, err = _parse_json_tolerant(raw)

    if err or not objects:
        st.error(f"❌ Could not parse JSON: {err}")
        st.code(raw[:500], language="json")
        return

    data = _flatten_chapter_json(objects[0])

    # ── Session state key for this chapter ────────────────────────────────────
    sk = f"ch_fix_{chapter_id}"
    if sk not in st.session_state:
        st.session_state[sk] = data

    d = st.session_state[sk]

    # ── Check what's missing ──────────────────────────────────────────────────
    needs_goal = not d.get("goal", "").strip()
    needs_arc = not d.get("chapter_arc", "").strip()
    subtopics = d.get("subtopics", [])
    subs_needing_goal = [i for i, s in enumerate(subtopics) if not s.get("goal", "").strip()]

    has_issues = needs_goal or needs_arc or subs_needing_goal

    # ── Preview header ────────────────────────────────────────────────────────
    st.success(f"✅ Parsed: **Chapter {d.get('number')} — {d.get('title')}** · {len(subtopics)} subtopics found")

    if not has_issues:
        st.info("All required fields are present. Ready to import.")
        if st.button("Import Chapter", type="primary", key=f"import_ch_{chapter_id}"):
            result = api.import_chapterization(chapter_id, d)
            if result:
                st.success(f"Imported: {result.get('title')} — {result.get('subtopics_created')} subtopics, arc set ✅")
                st.session_state.pop(sk, None)
                st.rerun()
        return

    # ── Fix missing fields ────────────────────────────────────────────────────
    st.warning(f"⚠️ {('goal, ' if needs_goal else '') + ('chapter_arc, ' if needs_arc else '') + (f'{len(subs_needing_goal)} subtopic goals' if subs_needing_goal else '')} need to be filled in before import.")

    with st.expander("📝 Fill in missing fields", expanded=True):

        if needs_goal:
            st.markdown("**Chapter Goal** — What must this chapter prove? How does it serve the thesis?")
            goal_val = st.text_area(
                "Chapter Goal", value=d.get("goal", ""),
                height=80, key=f"ch_goal_{chapter_id}",
                placeholder="e.g. Establish the theoretical and historical foundations for the feminist reading of post-independence Indian English fiction."
            )
            d["goal"] = goal_val

        if needs_arc:
            st.markdown("**Chapter Arc** *(150–200 words)* — How do all subtopics connect argumentatively?")
            st.caption("Describe the argumentative movement: what each subtopic establishes, how they build on each other, and what the chapter achieves by the end. This is injected into every Architect prompt for this chapter.")
            arc_val = st.text_area(
                "Chapter Arc", value=d.get("chapter_arc", ""),
                height=160, key=f"ch_arc_{chapter_id}",
                placeholder=(
                    "This chapter opens by situating the research within the broader context of Indian feminist literary criticism (1.1–1.2), "
                    "establishing that literature functions as a formative force rather than a passive mirror. "
                    "It then narrows to the specific problem: how patriarchal conditioning and cultural idealization suppress female subjectivity (1.6–1.8). "
                    "The Lacanian framework (1.8.1–1.8.2) provides the theoretical anchor for understanding identity erosion. "
                    "The chapter concludes by defining the key theoretical terms — feminism, patriarchy, postcolonialism, intersectionality — "
                    "that will operate throughout the thesis (1.10), ensuring the reader enters Chapter 2 with a stable conceptual vocabulary."
                )
            )
            d["chapter_arc"] = arc_val

        if subs_needing_goal:
            st.markdown(f"**Subtopic Goals** — {len(subs_needing_goal)} subtopics need a goal:")
            st.caption("Keep each goal to 1–2 sentences: what must this subtopic argue or establish?")

            for i in subs_needing_goal:
                s = subtopics[i]
                col1, col2 = st.columns([1, 3])
                with col1:
                    st.markdown(f"`{s['number']}`  \n{s['title']}")
                with col2:
                    goal = st.text_input(
                        f"Goal for {s['number']}",
                        value=s.get("goal", ""),
                        key=f"sub_goal_{chapter_id}_{i}",
                        placeholder=f"Establish / argue / demonstrate ..."
                    )
                    subtopics[i]["goal"] = goal
                    pos = st.text_input(
                        f"Role in arc (optional) — {s['number']}",
                        value=s.get("position_in_argument", ""),
                        key=f"sub_pos_{chapter_id}_{i}",
                        placeholder="e.g. Opens the chapter by grounding the argument historically."
                    )
                    subtopics[i]["position_in_argument"] = pos

        d["subtopics"] = subtopics
        st.session_state[sk] = d

        # ── Re-check after edits ──────────────────────────────────────────────
        still_missing_goal = not d.get("goal", "").strip()
        still_missing_arc = not d.get("chapter_arc", "").strip()
        still_missing_sub_goals = [s["number"] for s in d["subtopics"] if not s.get("goal", "").strip()]

        if still_missing_goal or still_missing_arc or still_missing_sub_goals:
            if still_missing_sub_goals:
                st.caption(f"Still missing goals for: {', '.join(still_missing_sub_goals)}")
            st.button("Import Chapter", disabled=True, key=f"import_ch_dis_{chapter_id}",
                      help="Fill in all required fields above first.")
        else:
            arc_words = len(d["chapter_arc"].split())
            if arc_words < 100:
                st.caption(f"⚠️ Chapter arc is only {arc_words} words. Aim for 150–200 for best results.")

            if st.button("✅ Import Chapter", type="primary", key=f"import_ch_{chapter_id}"):
                result = api.import_chapterization(chapter_id, d)
                if result:
                    st.success(
                        f"Imported: **{result.get('title')}** — "
                        f"{result.get('subtopics_created')} subtopics, arc set ✅"
                    )
                    st.session_state.pop(sk, None)
                    st.rerun()

    # ── Subtopics preview (collapsed) ─────────────────────────────────────────
    with st.expander(f"Preview all {len(subtopics)} subtopics", expanded=False):
        for s in subtopics:
            goal_ok = "✅" if s.get("goal", "").strip() else "⬜"
            st.markdown(f"{goal_ok} `{s['number']}` — {s['title']}")


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC — render_source_import_tab
# ══════════════════════════════════════════════════════════════════════════════

def render_source_import_tab():
    """
    Batch source import — upload multiple source.json files at once.

    The backend auto-patches missing fields (defaults for author, title,
    source_type, key_claims, themes) and sweeps extra fields into an
    'additional' column so nothing is lost and nothing crashes.
    """
    st.caption(
        "Upload one or more `source.json` files. Each JSON = 1 source group "
        "+ all chapters + all index cards. Missing fields are auto-filled "
        "by the backend; extra fields are preserved."
    )
    st.info(
        "**SPO stores metadata only.** The actual PDFs go to NotebookLM, not here. "
        "The `file_name` field in each chapter entry is the PDF name you will upload to NotebookLM.",
        icon="ℹ️"
    )

    uploaded_files = st.file_uploader(
        "Upload source JSON(s)", type="json",
        accept_multiple_files=True, key="src_json_batch_upload"
    )
    if not uploaded_files:
        return

    # ── Parse all files ───────────────────────────────────────────────────────
    parsed = []  # list of (filename, data_dict, error_string_or_None)
    for f in uploaded_files:
        raw = f.read().decode("utf-8")
        objects, err = _parse_json_tolerant(raw)
        if err or not objects:
            parsed.append((f.name, None, err or "No valid JSON found"))
            continue
        data = _merge_source_responses(objects)
        # Frontend normalization (field renaming for preview)
        data["chapters"] = [_normalize_chapter_entry(ch) for ch in data.get("chapters", [])]
        parsed.append((f.name, data, None))

    # ── Summary ───────────────────────────────────────────────────────────────
    good = [(name, data) for name, data, err in parsed if err is None]
    bad  = [(name, err)  for name, data, err in parsed if err is not None]

    st.markdown(f"**{len(uploaded_files)} file(s) selected** · "
                f"✅ {len(good)} parseable · ❌ {len(bad)} failed")

    # Show parse errors
    if bad:
        with st.expander(f"❌ {len(bad)} file(s) could not be parsed", expanded=True):
            for name, err in bad:
                st.error(f"**{name}** — {err}")

    # Show preview of parseable files
    if good:
        with st.expander(f"Preview {len(good)} source(s)", expanded=True):
            for name, data in good:
                author = str(data.get("author") or "Unknown Author")
                year = data.get("year", "?")
                title = str(data.get("title") or "Untitled Work")
                ch_count = len(data.get("chapters", []))
                st.markdown(f"- **{author} ({year})** — {title} · {ch_count} chapter(s) · `{name}`")

    # ── Import button ─────────────────────────────────────────────────────────
    if not good:
        st.button("Import All", disabled=True, key="do_batch_import",
                  help="No valid files to import.")
        return

    if st.button(f"✅ Import {len(good)} Source(s)", type="primary",
                 use_container_width=True, key="do_batch_import"):
        progress = st.progress(0, text="Importing...")
        results = []
        errors = []

        for idx, (name, data) in enumerate(good):
            try:
                result = api.import_source(data)
                if result:
                    results.append((name, result))
                else:
                    errors.append((name, "API returned empty response"))
            except Exception as e:
                errors.append((name, str(e)))
            progress.progress((idx + 1) / len(good),
                              text=f"Imported {idx + 1} / {len(good)}...")

        progress.empty()

        # Show results
        if results:
            st.success(f"✅ **{len(results)} / {len(good)}** sources imported successfully!")
            for name, result in results:
                st.markdown(
                    f"- ✅ **{result.get('title', '?')}** — "
                    f"{result.get('sources_created', 0)} chapters indexed · `{name}`"
                )

        if errors:
            st.error(f"❌ {len(errors)} file(s) failed to import:")
            for name, err in errors:
                st.markdown(f"- ❌ **{name}** — {err}")

        if results:
            st.rerun()
