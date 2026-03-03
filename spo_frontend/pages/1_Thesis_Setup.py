"""
Page: Thesis Setup
Manage your own thesis — synopsis, chapters, and subtopics.
"""

import streamlit as st
import api
import ui

st.set_page_config(page_title="Thesis Setup · SPO", page_icon="📚", layout="wide")
ui.page_header("📚 Thesis Setup", "Define your thesis structure — the big picture injected into every prompt.")

# ══════════════════════════════════════════════════════════════════════════════
# SYNOPSIS
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Thesis Synopsis")
st.caption("Written once. Injected into every Architect Mega-Prompt. The spine of all Task.md generation.")

synopsis = api.get_synopsis()

with st.form("synopsis_form"):
    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Thesis Title", value=synopsis.get("title", "") if synopsis else "")
        author = st.text_input("Author", value=synopsis.get("author", "") if synopsis else "")
    with col2:
        field = st.text_input("Field / Discipline", value=synopsis.get("field", "") if synopsis else "",
                               placeholder="e.g. Indian English Literature")
        framework = st.text_input("Theoretical Framework", value=synopsis.get("theoretical_framework", "") if synopsis else "",
                                   placeholder="e.g. Postcolonial feminism")

    central_argument = st.text_area(
        "Central Argument ★",
        value=synopsis.get("central_argument", "") if synopsis else "",
        height=120,
        placeholder="The single core argument of your entire thesis. 2–4 sentences. This is what the whole thesis is trying to prove.",
        help="This is the most important field. Every Task.md Claude generates will be anchored to this."
    )
    scope = st.text_area(
        "Scope and Limits",
        value=synopsis.get("scope_and_limits", "") if synopsis else "",
        height=80,
        placeholder="What the thesis explicitly covers and does NOT cover.",
    )

    if st.form_submit_button("Save Synopsis", use_container_width=True, type="primary"):
        if not all([title, author, field, central_argument]):
            st.error("Title, Author, Field, and Central Argument are required.")
        else:
            result = api.save_synopsis({
                "title": title, "author": author, "field": field,
                "central_argument": central_argument,
                "theoretical_framework": framework or None,
                "scope_and_limits": scope or None,
            })
            if result:
                ui.success("Synopsis saved.")
                st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# CHAPTERS
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Chapters & Subtopics")
st.caption("Each chapter needs a goal. Each subtopic is one NotebookLM writing session.")

chapters = api.list_chapters()

# Add new chapter
with st.expander("➕ Add Chapter", expanded=not chapters):
    with st.form("add_chapter_form"):
        col1, col2 = st.columns([1, 4])
        with col1:
            ch_num = st.number_input("Number", min_value=1, max_value=20, value=len(chapters) + 1, step=1)
        with col2:
            ch_title = st.text_input("Chapter Title", placeholder="e.g. Historical Background of Indian Women's Writing")
        ch_goal = st.text_area(
            "Chapter Goal ★",
            height=100,
            placeholder="What must this chapter prove? How does it serve the thesis argument? 3–5 sentences.",
            help="Injected alongside the synopsis when Claude generates Task.md."
        )
        if st.form_submit_button("Add Chapter", use_container_width=True):
            if not ch_title or not ch_goal:
                st.error("Title and Goal are required.")
            else:
                result = api.create_chapter({"number": int(ch_num), "title": ch_title, "goal": ch_goal})
                if result:
                    ui.success(f"Chapter {ch_num} added.")
                    st.rerun()

st.divider()

# Display chapters with subtopics
if not chapters:
    ui.info("No chapters yet. Add your first chapter above.")
else:
    for chapter in sorted(chapters, key=lambda c: c.get("number", 0)):
        ch_id = chapter["chapter_id"]
        subtopics = chapter.get("subtopics", [])
        label = f"Ch.{chapter['number']} — {chapter['title']}  ({len(subtopics)} subtopics)"

        with st.expander(label, expanded=False):
            # Chapter goal display + delete
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**Goal:** {chapter['goal']}")
            with col2:
                if st.button("🗑️ Delete Chapter", key=f"del_ch_{ch_id}"):
                    api.delete_chapter(ch_id)
                    ui.success("Chapter deleted.")
                    st.rerun()

            st.divider()

            # Subtopics table
            if subtopics:
                st.markdown("**Subtopics**")
                for sub in subtopics:
                    sub_id = sub["subtopic_id"]
                    sc1, sc2, sc3 = st.columns([1, 5, 1])
                    with sc1:
                        st.markdown(f"`{sub['number']}`")
                    with sc2:
                        st.markdown(f"**{sub['title']}**")
                        st.caption(sub.get("goal", ""))
                        if sub.get("position_in_argument"):
                            st.caption(f"*Position: {sub['position_in_argument']}*")
                    with sc3:
                        if st.button("🗑️", key=f"del_sub_{ch_id}_{sub_id}", help="Delete subtopic"):
                            api.delete_subtopic(ch_id, sub_id)
                            st.rerun()
                st.divider()

            # Add subtopic form
            with st.form(f"add_sub_{ch_id}"):
                st.markdown("**Add Subtopic**")
                sc1, sc2 = st.columns([1, 4])
                with sc1:
                    sub_num = st.text_input("Number", placeholder="1.3.2", key=f"subnum_{ch_id}")
                with sc2:
                    sub_title = st.text_input("Title", key=f"subtitle_{ch_id}")
                sub_goal = st.text_area("Goal ★", height=80,
                                         placeholder="What must this subtopic argue or establish?",
                                         key=f"subgoal_{ch_id}")
                sub_pos = st.text_input("Position in Argument (optional)",
                                         placeholder="e.g. Establishes the historical gap the chapter fills",
                                         key=f"subpos_{ch_id}")
                if st.form_submit_button("Add Subtopic", use_container_width=True):
                    if not sub_num or not sub_title or not sub_goal:
                        st.error("Number, Title and Goal are required.")
                    else:
                        result = api.add_subtopic(ch_id, {
                            "number": sub_num,
                            "title": sub_title,
                            "goal": sub_goal,
                            "position_in_argument": sub_pos or None,
                        })
                        if result:
                            ui.success(f"Subtopic {sub_num} added.")
                            st.rerun()
