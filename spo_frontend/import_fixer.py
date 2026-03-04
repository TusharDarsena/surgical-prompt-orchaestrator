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
    Drop-in replacement for the `with tab_import:` block in 2_Source_Library.py.

    Handles:
    - Invalid JSON with 'response N' prefixes
    - Multiple JSON objects (merges chapters from all responses)
    - Missing source_type (offers dropdown to pick)
    - Missing key_claims or themes on individual chapters (inline fix)
    """
    SOURCE_TYPES = ["thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"]

    st.caption(
        "Generate source.json by uploading PDF chapters to NotebookLM and using "
        "`prompts/generate_source_json.txt`. One JSON = 1 group + all sources + all index cards."
    )
    st.info(
        "**SPO stores metadata only.** The actual PDFs go to NotebookLM, not here. "
        "The `file_name` field in each chapter entry is the PDF name you will upload to NotebookLM.",
        icon="ℹ️"
    )

    uploaded_src = st.file_uploader("Upload source.json", type="json", key="src_json_upload")
    if not uploaded_src:
        return

    raw = uploaded_src.read().decode("utf-8")
    objects, err = _parse_json_tolerant(raw)

    if err or not objects:
        st.error(f"❌ Could not parse JSON — {err}")
        with st.expander("Show raw content"):
            st.code(raw[:1000])
        return

    # Merge multi-response NotebookLM output
    data = _merge_source_responses(objects)

    if len(objects) > 1:
        st.info(f"ℹ️ Found {len(objects)} JSON blocks (NotebookLM multi-response) — merged into one source with {len(data.get('chapters', []))} unique chapters.")

    # Normalize chapter entries
    chapters = [_normalize_chapter_entry(ch) for ch in data.get("chapters", [])]
    data["chapters"] = chapters

    # ── Session state ─────────────────────────────────────────────────────────
    sk = "src_fix"
    if sk not in st.session_state or st.session_state.get("src_fix_name") != uploaded_src.name:
        st.session_state[sk] = data
        st.session_state["src_fix_name"] = uploaded_src.name

    d = st.session_state[sk]

    # ── Top-level field issues ────────────────────────────────────────────────
    needs_title = not d.get("title", "").strip()
    needs_author = not d.get("author", "").strip()
    needs_type = not d.get("source_type", "").strip() or d.get("source_type") not in SOURCE_TYPES

    # ── Chapter-level issues ──────────────────────────────────────────────────
    chapters = d.get("chapters", [])
    ch_issues = []
    for i, ch in enumerate(chapters):
        problems = []
        if not ch.get("key_claims"):
            problems.append("key_claims")
        if not ch.get("themes"):
            problems.append("themes")
        if problems:
            ch_issues.append((i, ch.get("label", f"Chapter {i+1}"), problems))

    has_issues = needs_title or needs_author or needs_type or ch_issues

    # ── Status header ─────────────────────────────────────────────────────────
    if not has_issues:
        st.success(f"✅ **{d.get('author', '?')} ({d.get('year', '?')})** — {d.get('title', '?')}")
    else:
        st.warning(f"⚠️ **{d.get('author', '?')} ({d.get('year', '?')})** — {d.get('title', '?')} · Some fields need attention.")

    # ── Fix top-level fields ──────────────────────────────────────────────────
    if needs_title or needs_author or needs_type:
        with st.expander("📝 Fix work-level fields", expanded=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            with c1:
                if needs_title:
                    d["title"] = st.text_input("Title ★", value=d.get("title", ""), key="src_fix_title")
            with c2:
                if needs_author:
                    d["author"] = st.text_input("Author ★", value=d.get("author", ""), key="src_fix_author")
            with c3:
                if needs_type:
                    current = d.get("source_type", "")
                    idx = SOURCE_TYPES.index(current) if current in SOURCE_TYPES else 0
                    d["source_type"] = st.selectbox("Source Type ★", SOURCE_TYPES, index=idx, key="src_fix_type")
            st.session_state[sk] = d

    # ── Fix chapter-level issues ──────────────────────────────────────────────
    if ch_issues:
        with st.expander(f"📝 Fix {len(ch_issues)} chapter(s) with missing index card fields", expanded=True):
            st.caption("Key Claims and Themes are required for each chapter — they feed directly into Architect prompts.")

            for i, label, problems in ch_issues:
                ch = chapters[i]
                st.markdown(f"**`{label}`** — {ch.get('title', '')}")

                if "key_claims" in problems:
                    existing = "\n".join(ch.get("key_claims") or [])
                    raw_claims = st.text_area(
                        "Key Claims ★ (one per line)",
                        value=existing,
                        height=120,
                        key=f"src_claims_{i}",
                        placeholder=(
                            "Argues that Deshpande represents the third phase of Indian feminism\n"
                            "Claims that domestic circumscription catalyzed her writing process"
                        )
                    )
                    chapters[i]["key_claims"] = [c.strip() for c in raw_claims.strip().split("\n") if c.strip()]

                if "themes" in problems:
                    existing_themes = ", ".join(ch.get("themes") or [])
                    raw_themes = st.text_input(
                        "Themes ★ (comma-separated, snake_case)",
                        value=existing_themes,
                        key=f"src_themes_{i}",
                        placeholder="third_phase_feminism, domestic_confinement, literary_patriarchy"
                    )
                    chapters[i]["themes"] = [t.strip() for t in raw_themes.split(",") if t.strip()]

                st.divider()

            d["chapters"] = chapters
            st.session_state[sk] = d

    # ── Preview ───────────────────────────────────────────────────────────────
    with st.expander(f"Preview — {len(chapters)} document(s)", expanded=not has_issues):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**{d.get('author', '?')} ({d.get('year', '?')})** — {d.get('title', '?')}")
            st.caption(f"Type: {d.get('source_type', '?')} · {d.get('institution_or_publisher', '')}")
            if d.get("description"):
                st.markdown(f"*{d['description']}*")
        with col2:
            for ch in d.get("chapters", []):
                card_ok = bool(ch.get("key_claims")) and bool(ch.get("themes"))
                badge = "✅" if card_ok else "⚠️ incomplete"
                fname = f" · `{ch.get('file_name')}`" if ch.get("file_name") else ""
                st.markdown(f"- `{ch.get('label', '?')}` {badge}{fname}")

    # ── Import button ─────────────────────────────────────────────────────────
    # Re-check current state
    still_issues = (
        not d.get("title", "").strip()
        or not d.get("author", "").strip()
        or d.get("source_type", "") not in SOURCE_TYPES
        or any(not ch.get("key_claims") or not ch.get("themes") for ch in d.get("chapters", []))
    )

    if still_issues:
        st.button("Import Source JSON", disabled=True, key="do_import_src",
                  help="Fix all flagged fields above first.")
    else:
        if st.button("✅ Import Source JSON", type="primary", use_container_width=True, key="do_import_src"):
            result = api.import_source(d)
            if result:
                st.success(
                    f"Imported: **{result.get('title')}** — "
                    f"{result.get('sources_created')} sources, all indexed. ✅"
                )
                st.session_state.pop(sk, None)
                st.session_state.pop("src_fix_name", None)
                st.rerun()
