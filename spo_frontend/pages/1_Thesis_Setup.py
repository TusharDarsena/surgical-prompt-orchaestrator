"""
Page: Thesis Setup
Two paths:
  Primary  — JSON import (faster, richer, recommended for initial setup)
  Fallback — Manual forms (for patches and corrections)
"""

import json
import streamlit as st
import api
import ui

st.set_page_config(page_title="Thesis Setup · SPO", page_icon="📚", layout="wide")
ui.page_header("📚 Thesis Setup", "Set up your thesis structure — synopsis, chapters, subtopics.")

# ── Import status banner ───────────────────────────────────────────────────────
synopsis = api.get_synopsis()
chapters = api.list_chapters()
chapters_without_arc = [c for c in chapters if not c.get("chapter_arc")]

if synopsis and chapters and not chapters_without_arc:
    st.success(
        f"Setup complete. {len(chapters)} chapters · "
        f"{sum(len(c.get('subtopics',[])) for c in chapters)} subtopics · "
        "All chapter arcs set.",
        icon="✅"
    )
elif synopsis:
    missing = []
    if chapters_without_arc:
        missing.append(f"{len(chapters_without_arc)} chapter(s) missing arc")
    if not chapters:
        missing.append("no chapters imported")
    st.warning(f"Partially set up: {' · '.join(missing)}", icon="⚠️")
else:
    st.info("Start by importing your thesis.json below.", icon="👇")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SYNOPSIS
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("1 — Thesis Synopsis")

# Persistent synopsis preview (always visible if data exists)
if synopsis:
    with st.expander("📋 Current Synopsis", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Title:** {synopsis.get('title', '—')}")
            st.markdown(f"**Author:** {synopsis.get('author', synopsis.get('researcher', '—'))}")
            st.markdown(f"**Field:** {synopsis.get('field', '—')}")
            st.markdown(f"**Temporal scope:** {synopsis.get('temporal_scope', '—')}")
        with col2:
            frameworks = synopsis.get("theoretical_frameworks", [])
            if not frameworks and synopsis.get("methodology"):
                frameworks = synopsis["methodology"].get("theoretical_frameworks", [])
            st.markdown(f"**Frameworks:** {', '.join(frameworks) if frameworks else '—'}")
            st.markdown(f"**Themes:** {', '.join(synopsis.get('central_themes', [])) or '—'}")
        # Show core_argument or central_argument (whichever exists)
        arg = synopsis.get("core_argument") or synopsis.get("central_argument", "—")
        st.markdown("**Central argument:**")
        st.info(arg)

tab_import, tab_manual = st.tabs(["📥 Import synopsis_context.json  *(recommended)*", "✏️ Manual form"])

with tab_import:
    st.caption(
        "Generate synopsis_context.json by giving Claude your synopsis document with the prompt "
        "in `prompts/generate_synopsis_context_json.txt`. Review the JSON, then upload here."
    )
    uploaded = st.file_uploader("Upload synopsis_context.json", type="json", key="synopsis_upload")
    if uploaded:
        try:
            data = json.load(uploaded)
            with st.expander("Preview parsed data", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Title:** {data.get('title', '—')}")
                    st.markdown(f"**Author:** {data.get('author', '—')}")
                    st.markdown(f"**Field:** {data.get('field', '—')}")
                    st.markdown(f"**Temporal scope:** {data.get('temporal_scope', '—')}")
                with col2:
                    st.markdown(f"**Frameworks:** {', '.join(data.get('theoretical_frameworks', []))}")
                    st.markdown(f"**Themes:** {', '.join(data.get('central_themes', []))}")
                st.markdown("**Central argument:**")
                st.info(data.get("core_argument") or data.get("central_argument", "—"))

            if st.button("Import Thesis JSON", type="primary", use_container_width=True):
                result = api.post("/import/thesis", data)
                if result:
                    ui.success("Thesis imported.")
                    st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

with tab_manual:
    st.caption("Use this to create or patch the synopsis field by field.")
    # Read both core_argument and central_argument (whichever exists)
    existing_arg = ""
    if synopsis:
        existing_arg = synopsis.get("core_argument") or synopsis.get("central_argument", "")
    with st.form("synopsis_form"):
        col1, col2 = st.columns(2)
        with col1:
            title = st.text_input("Title", value=synopsis.get("title", "") if synopsis else "")
            author = st.text_input("Author", value=synopsis.get("author", synopsis.get("researcher", "")) if synopsis else "")
            field = st.text_input("Field", value=synopsis.get("field", "") if synopsis else "")
        with col2:
            temporal = st.text_input(
                "Temporal Scope",
                value=synopsis.get("temporal_scope", "") if synopsis else "",
                placeholder="e.g. 1947–1990"
            )
            existing_frameworks = []
            if synopsis:
                existing_frameworks = synopsis.get("theoretical_frameworks", [])
                if not existing_frameworks and synopsis.get("methodology"):
                    existing_frameworks = synopsis["methodology"].get("theoretical_frameworks", [])
            frameworks_raw = st.text_input(
                "Theoretical Frameworks (comma-separated)",
                value=", ".join(existing_frameworks),
            )
        central_argument = st.text_area(
            "Central Argument ★", height=120,
            value=existing_arg,
            placeholder="The single core argument. 2–4 sentences. Specific claim, not description."
        )
        scope = st.text_area(
            "Scope and Limits", height=80,
            value=synopsis.get("scope_and_limits", "") if synopsis else ""
        )
        if st.form_submit_button("Save Synopsis", use_container_width=True, type="primary"):
            if not all([title, author, field, central_argument]):
                st.error("Title, Author, Field, and Central Argument are required.")
            else:
                result = api.save_synopsis({
                    "title": title, "author": author, "field": field,
                    "central_argument": central_argument,
                    "theoretical_frameworks": [f.strip() for f in frameworks_raw.split(",") if f.strip()],
                    "temporal_scope": temporal or None,
                    "scope_and_limits": scope or None,
                })
                if result:
                    ui.success("Synopsis saved.")
                    st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# CHAPTERS
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("2 — Chapters & Subtopics")

tab_ch_import, tab_ch_manual = st.tabs([
    "📥 Import chapter JSON",
    "✏️ Manual form"
])

with tab_ch_import:
    st.caption(
        "Upload the chapterization JSON generated by Claude. "
        "The chapter_id is auto-detected from the `number` field in the JSON."
    )
    ch_uploaded = st.file_uploader("Upload chapterization.json", type="json", key="ch_upload")
    if ch_uploaded:
        try:
            ch_data = json.load(ch_uploaded)

            # Handle both single object and array of chapters
            chapters_list = ch_data if isinstance(ch_data, list) else [ch_data]

            for ch_item in chapters_list:
                ch_num = ch_item.get("number")
                if ch_num is None:
                    st.error("JSON is missing the `number` field. Each chapter must have a `number`.")
                    st.stop()

                auto_ch_id = f"ch{ch_num}"
                subtopics = ch_item.get("subtopics", [])
                source_count = sum(len(s.get("source_ids", [])) for s in subtopics)

                with st.expander(f"Preview — Chapter {ch_num}: {ch_item.get('title', '—')}", expanded=True):
                    st.markdown(f"**Chapter ID:** `{auto_ch_id}` *(auto-generated)*")
                    st.markdown(f"**Goal:** {ch_item.get('goal', '—')}")
                    st.markdown(f"**Subtopics:** {len(subtopics)}")
                    st.markdown(f"**Source guidance entries:** {source_count}")
                    if ch_item.get("chapter_arc"):
                        st.caption(f"**Arc:** {ch_item['chapter_arc'][:200]}...")

            if st.button("Import Chapterization", type="primary", use_container_width=True):
                if len(chapters_list) == 1:
                    ch_item = chapters_list[0]
                    auto_ch_id = f"ch{ch_item['number']}"
                    result = api.import_chapterization(auto_ch_id, ch_item)
                else:
                    result = api.import_chapterization_bulk(chapters_list)
                if result:
                    ui.success(f"Chapterization imported successfully.")
                    st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")


with tab_ch_manual:
    st.caption("Manual chapter and subtopic entry — for corrections or small additions.")

    with st.expander("➕ Add Chapter", expanded=not chapters):
        with st.form("add_chapter_form"):
            col1, col2 = st.columns([1, 4])
            with col1:
                ch_num = st.number_input("Number", min_value=1, max_value=20,
                                          value=len(chapters) + 1, step=1)
            with col2:
                ch_title = st.text_input("Chapter Title")
            ch_goal = st.text_area("Chapter Goal ★", height=100,
                                    placeholder="What must this chapter prove?")
            ch_arc = st.text_area(
                "Chapter Arc (optional — add via JSON import for best results)",
                height=120,
                placeholder="150–200 words. How all subtopics connect argumentatively."
            )
            if st.form_submit_button("Add Chapter", use_container_width=True):
                if not ch_title or not ch_goal:
                    st.error("Title and Goal are required.")
                else:
                    result = api.create_chapter({
                        "number": int(ch_num), "title": ch_title,
                        "goal": ch_goal, "chapter_arc": ch_arc or None
                    })
                    if result:
                        ui.success(f"Chapter {ch_num} added.")
                        st.rerun()

st.divider()

# ── Chapter list with arc status ───────────────────────────────────────────────
if not chapters:
    ui.info("No chapters yet.")
else:
    for chapter in sorted(chapters, key=lambda c: c.get("number", 0)):
        ch_id = chapter["chapter_id"]
        subtopics = chapter.get("subtopics", [])
        has_arc = bool(chapter.get("chapter_arc"))
        arc_badge = "✅ Arc" if has_arc else "⚠️ No arc"
        label = f"Ch.{chapter['number']} — {chapter['title']}  |  {arc_badge}  |  {len(subtopics)} subtopics"

        with st.expander(label, expanded=False):
            col1, col2, col3 = st.columns([5, 1, 1])
            with col1:
                st.markdown(f"**Goal:** {chapter['goal']}")
            with col2:
                if st.button("✏️", key=f"edit_ch_btn_{ch_id}", help="Edit chapter"):
                    st.session_state[f"editing_ch_{ch_id}"] = True
            with col3:
                if st.button("🗑️", key=f"del_ch_{ch_id}", help="Delete chapter"):
                    api.delete_chapter(ch_id)
                    st.rerun()

            # Inline chapter edit form
            if st.session_state.get(f"editing_ch_{ch_id}"):
                with st.form(f"edit_ch_form_{ch_id}"):
                    st.markdown("**Edit Chapter**")
                    e_title = st.text_input("Title", value=chapter.get("title", ""))
                    e_goal = st.text_area("Goal", value=chapter.get("goal", ""), height=100)
                    e_arc = st.text_area(
                        "Chapter Arc",
                        value=chapter.get("chapter_arc", "") or "",
                        height=150,
                        help="150–200 words. How all subtopics connect argumentatively."
                    )
                    eb1, eb2 = st.columns(2)
                    with eb1:
                        if st.form_submit_button("Save", use_container_width=True, type="primary"):
                            api.update_chapter(ch_id, {
                                "title": e_title,
                                "goal": e_goal,
                                "chapter_arc": e_arc or None,
                            })
                            st.session_state[f"editing_ch_{ch_id}"] = False
                            ui.success("Chapter updated.")
                            st.rerun()
                    with eb2:
                        if st.form_submit_button("Cancel", use_container_width=True):
                            st.session_state[f"editing_ch_{ch_id}"] = False
                            st.rerun()

            if has_arc:
                with st.expander("View chapter arc"):
                    st.markdown(chapter["chapter_arc"])
            else:
                st.warning(
                    "No chapter arc. Import chapterization.json for this chapter "
                    "or add it manually via the form above.",
                    icon="⚠️"
                )

            st.divider()

            if subtopics:
                st.markdown("**Subtopics:**")
                for sub in subtopics:
                    sub_id = sub["subtopic_id"]
                    sc1, sc2, sc3 = st.columns([1, 5, 1])
                    with sc1:
                        st.markdown(f"`{sub['number']}`")
                    with sc2:
                        st.markdown(f"**{sub['title']}**")
                        st.caption(sub.get("goal", ""))
                        if sub.get("position_in_argument"):
                            st.caption(f"*{sub['position_in_argument']}*")
                    with sc3:
                        if st.button("🗑️", key=f"del_sub_{ch_id}_{sub_id}"):
                            api.delete_subtopic(ch_id, sub_id)
                            st.rerun()
                st.divider()

            # Add subtopic manually
            with st.form(f"add_sub_{ch_id}"):
                st.markdown("**Add Subtopic Manually**")
                sc1, sc2 = st.columns([1, 4])
                with sc1:
                    sub_num = st.text_input("Number", placeholder="1.3.2", key=f"sn_{ch_id}")
                with sc2:
                    sub_title = st.text_input("Title", key=f"st_{ch_id}")
                sub_goal = st.text_area("Goal ★", height=80, key=f"sg_{ch_id}")
                sub_pos = st.text_input("Position in Argument", key=f"sp_{ch_id}")
                if st.form_submit_button("Add Subtopic"):
                    if not sub_num or not sub_title or not sub_goal:
                        st.error("Number, Title and Goal are required.")
                    else:
                        result = api.add_subtopic(ch_id, {
                            "number": sub_num, "title": sub_title,
                            "goal": sub_goal, "position_in_argument": sub_pos or None,
                        })
                        if result:
                            ui.success(f"Subtopic {sub_num} added.")
                            st.rerun()