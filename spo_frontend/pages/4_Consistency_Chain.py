"""
Page: Consistency Chain
View the full argument thread of a chapter — what was argued in each completed section.
"""

import streamlit as st
import api
import ui

st.set_page_config(page_title="Consistency Chain · SPO", page_icon="🔗", layout="wide")
ui.page_header("🔗 Consistency Chain", "The running log of what was argued. Keeps sections coherent.")

st.caption(
    "After completing each section, you save a summary in **Write a Section**. "
    "This page shows the full thread — useful for spotting argument drift or gaps."
)

chapters = api.list_chapters()
if not chapters:
    ui.info("No chapters yet. Set up your thesis first.")
    st.stop()

chapter_options = {f"Ch.{c['number']} — {c['title']}": c for c in sorted(chapters, key=lambda x: x["number"])}
selected_label = st.selectbox("Select Chapter", list(chapter_options.keys()))
chapter = chapter_options[selected_label]
chapter_id = chapter["chapter_id"]
subtopics = chapter.get("subtopics", [])

st.divider()

# ── Progress overview ──────────────────────────────────────────────────────────
chain = api.get_chapter_chain(chapter_id)
completed_ids = {s.get("subtopic_id") for s in chain}

# Fetch ALL blueprints in one round-trip, then build a lookup set.
# This replaces the previous N-per-subtopic api.get_task_blueprint() calls
# inside the loop below, which made the page scale poorly with many subtopics.
_all_blueprints = api.list_task_blueprints()
saved_blueprint_ids = {
    f"{b['chapter_id']}__{b['subtopic_id']}"
    for b in _all_blueprints.get("blueprints", [])
}

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Subtopics Defined", len(subtopics))
with col2:
    st.metric("Sections Complete", len(chain))
with col3:
    pct = int(len(chain) / len(subtopics) * 100) if subtopics else 0
    st.metric("Progress", f"{pct}%")

# Progress bar
if subtopics:
    st.progress(len(chain) / len(subtopics) if subtopics else 0)

st.divider()

# ── Subtopic-by-subtopic view ──────────────────────────────────────────────────
if not subtopics:
    ui.info("No subtopics defined in this chapter.")
    st.stop()

st.subheader("Section-by-Section Thread")

for i, sub in enumerate(subtopics):
    sub_id = sub["subtopic_id"]
    is_done = sub_id in completed_ids

    # Find summary if exists
    summary = next((s for s in chain if s.get("subtopic_id") == sub_id), None)

    status_icon = "✅" if is_done else "⬜"
    label = f"{status_icon}  {sub['number']} — {sub['title']}"

    with st.expander(label, expanded=is_done and i == len(chain) - 1):
        col_l, col_r = st.columns([5, 1])

        with col_l:
            st.caption(f"**Goal:** {sub.get('goal', '')}")

        with col_r:
            if is_done:
                st.markdown(":green[Complete]")
            else:
                st.markdown(":gray[Pending]")

        if summary:
            st.markdown("**What was argued:**")
            st.markdown(f"> {summary['core_argument_made']}")

            if summary.get("key_terms_established"):
                terms = ", ".join(f"`{t}`" for t in summary["key_terms_established"])
                st.markdown(f"**Terms established:** {terms}")

            if summary.get("sources_used"):
                sources = ", ".join(summary["sources_used"])
                st.markdown(f"**Sources used:** {sources}")

            if summary.get("what_next_section_must_build_on"):
                st.info(f"**Bridge to next section:** {summary['what_next_section_must_build_on']}", icon="➡️")

            if st.button("🗑️ Delete Summary", key=f"del_sum_{sub_id}",
                          help="Delete to re-record after rewriting this section"):
                result = api.delete_consistency_summary(chapter_id, sub_id)
                if result:
                    ui.success("Summary deleted.")
                    st.rerun()
        else:
            st.caption("Not yet written. Go to **Write a Section** to complete this subtopic.")

        # O(1) set lookup — no HTTP call per subtopic
        has_blueprint = f"{chapter_id}__{sub_id}" in saved_blueprint_ids
        if has_blueprint:
            st.caption(f"📋 Task.md saved · {sub.get('number', '')}")
        else:
            st.caption("📋 No Task.md yet")

st.divider()

# ── Full chain as plain text (for copying) ────────────────────────────────────
if chain:
    st.subheader("Export: Full Argument Thread")
    st.caption("Copy this as a reference while writing. Paste into a doc or note.")

    lines = [f"# Argument Thread — {chapter['title']}\n"]
    for s in chain:
        lines.append(f"## {s.get('subtopic_number', '')} — {s.get('subtopic_title', '')}")
        lines.append(s.get("core_argument_made", ""))
        if s.get("key_terms_established"):
            lines.append(f"Terms: {', '.join(s['key_terms_established'])}")
        lines.append("")

    thread_text = "\n".join(lines)
    ui.copy_button(thread_text, label="📋 Copy Full Thread", key="copy_thread")
    st.text_area("Thread", value=thread_text, height=300, disabled=True)
