"""
Page: Write a Section
The full two-phase workflow:
  Phase 1 — Compile Architect prompt → paste into Claude → save Task.md
  Phase 2 — Compile NotebookLM prompt → paste into NotebookLM → save consistency summary
"""

import streamlit as st
import api
import ui

st.set_page_config(page_title="Write a Section · SPO", page_icon="✍️", layout="wide")
ui.page_header("✍️ Write a Section", "Two prompts. One for Claude. One for NotebookLM.")

# ── Select chapter + subtopic ──────────────────────────────────────────────────
chapters = api.list_chapters()
chapter_id, chapter, subtopic = ui.subtopic_selector(chapters)

if not subtopic:
    st.stop()

subtopic_id = subtopic["subtopic_id"]

# ── Status bar for this subtopic ───────────────────────────────────────────────
blueprint = api.get_task_blueprint(chapter_id, subtopic_id)
prev = api.get_previous_summary(chapter_id, subtopic_id)
suggested = api.get_suggested_sources(chapter_id, subtopic_id)
source_count = len(suggested.get("suggested_sources", []))

st.divider()
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Sources Tagged", source_count)
with col2:
    st.metric("Task.md Saved", "✅ Yes" if blueprint else "❌ No")
with col3:
    has_prev = bool(prev.get("summary"))
    st.metric("Previous Section", "✅ Found" if has_prev else "—  First section")
with col4:
    chain = api.get_chapter_chain(chapter_id)
    st.metric("Sections Done (Ch.)", len(chain))

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — ARCHITECT PROMPT
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Phase 1 — Architect Prompt for Claude")
st.caption("Compile → Copy → Paste into Claude → Get Task.md → Edit → Save below.")

with st.expander("ℹ️ What this prompt does", expanded=False):
    st.markdown("""
    Claude receives your thesis synopsis, chapter goal, subtopic definition,
    source index cards, and previous section context. It outputs a **Task.md
    blueprint** — Core Objective, Focus Points (each tied to a source),
    Key Terms, and Do Not Include.

    You edit that Task.md before saving — this is the human-in-the-loop step.
    """)

# Source selection
if source_count == 0:
    st.warning(
        "No sources are tagged for this subtopic. "
        "Go to **Source Library**, open an index card, and add this subtopic's ID "
        f"(`{subtopic_id}`) to the **Relevant Subtopics** field.",
        icon="⚠️"
    )

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    include_prev = st.checkbox(
        "Include previous section context",
        value=has_prev,
        help="Uncheck for the very first subtopic of a chapter."
    )

if st.button("⚙️ Compile Architect Prompt", use_container_width=True, type="primary", disabled=source_count == 0):
    with st.spinner("Compiling..."):
        result = api.compile_architect_prompt(chapter_id, subtopic_id, include_previous=include_prev)
    if result:
        st.session_state["architect_prompt"] = result.get("prompt", "")
        st.session_state["architect_meta"] = result.get("meta", {})

if "architect_prompt" in st.session_state and st.session_state["architect_prompt"]:
    meta = st.session_state.get("architect_meta", {})
    ui.warnings_box(meta.get("warnings", []))

    st.markdown("**Compiled Prompt — Copy and paste into Claude:**")
    ui.prompt_output_box(st.session_state["architect_prompt"], copy_key="copy_arch")

    # Show what was included
    with st.expander("📋 What was included in this prompt"):
        st.json({
            "chapter": meta.get("chapter"),
            "subtopic": meta.get("subtopic"),
            "sources_included": [s.get("label") for s in meta.get("sources_included", [])],
            "previous_section": meta.get("previous_section"),
        })

st.divider()

# ── Save Task.md ───────────────────────────────────────────────────────────────
st.subheader("Save Approved Task.md")
st.caption("Paste Claude's Task.md output below. Edit out fluff. Save when satisfied.")

if blueprint:
    st.success(f"Task.md already saved for this subtopic. Submitting again will overwrite it.", icon="✅")
    with st.expander("View saved Task.md"):
        st.markdown(blueprint.get("raw_markdown", ""))

with st.form("save_taskmd_form"):
    raw_md = st.text_area(
        "Task.md (paste Claude's output, then edit)",
        height=350,
        value=blueprint.get("raw_markdown", "") if blueprint else "",
        placeholder="""## Core Objective
Establish that pre-1947 male-authored texts constructed female characters as nationalist symbols.

## Focus Points
- [Argument 1]. [Sharma Ch.2]
- [Argument 2]. [Nair 1992]

## Key Terms to Use
nationalist idealization, representational gap

## Do Not Include
- Claims about pan-Indian feminist movement (Sharma Ch.2 only covers Bengali tradition)
- Post-independence context (covered in next section)""",
    )

    st.markdown("**Parsed fields** *(optional but improves NotebookLM prompt)*")
    col1, col2 = st.columns(2)
    with col1:
        core_obj = st.text_input(
            "Core Objective (1 sentence)",
            value=blueprint.get("core_objective", "") if blueprint else "",
            placeholder="Establish that pre-1947 male-authored texts..."
        )
        key_terms_raw = st.text_input(
            "Key Terms (comma-separated)",
            value=", ".join(blueprint.get("key_terms", [])) if blueprint else "",
            placeholder="nationalist idealization, representational gap"
        )
    with col2:
        word_count = st.number_input(
            "Target Word Count",
            min_value=0, max_value=5000,
            value=blueprint.get("word_count_target", 800) if blueprint else 800,
            step=100
        )

    focus_raw = st.text_area(
        "Focus Points (one per line)",
        value="\n".join(blueprint.get("focus_points", [])) if blueprint else "",
        height=120,
        placeholder="Argues X using [Sharma Ch.2]\nEstablishes Y via [Nair 1992]"
    )
    dont_raw = st.text_area(
        "Do Not Include (one per line)",
        value="\n".join(blueprint.get("do_not_include", [])) if blueprint else "",
        height=80,
        placeholder="Pan-Indian claims (source covers only Bengal)\nPost-independence context"
    )

    if st.form_submit_button("Save Task.md", use_container_width=True, type="primary"):
        if not raw_md.strip():
            st.error("Paste the Task.md content before saving.")
        else:
            data = {
                "raw_markdown": raw_md,
                "core_objective": core_obj or None,
                "focus_points": [f.strip() for f in focus_raw.split("\n") if f.strip()],
                "key_terms": [t.strip() for t in key_terms_raw.split(",") if t.strip()],
                "do_not_include": [d.strip() for d in dont_raw.split("\n") if d.strip()],
                "word_count_target": int(word_count) if word_count else None,
            }
            result = api.save_task_blueprint(chapter_id, subtopic_id, data)
            if result:
                ui.success("Task.md saved. Proceed to Phase 2.")
                st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — NOTEBOOKLM PROMPT
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("Phase 2 — NotebookLM Prompt")
st.caption("Compile → Upload PDFs to NotebookLM → Paste prompt → Get draft.")

if not blueprint:
    st.warning("Save an approved Task.md above before compiling the NotebookLM prompt.", icon="⚠️")
else:
    with st.expander("ℹ️ What to upload to NotebookLM", expanded=True):
        suggested_sources = suggested.get("suggested_sources", [])
        if suggested_sources:
            st.markdown("**Upload these PDFs to NotebookLM before pasting the prompt:**")
            for s in suggested_sources:
                fname = s.get("file_name") or s.get("label", "unnamed")
                st.markdown(f"- 📄 `{fname}`  —  *{s.get('title', '')}*")
        else:
            st.info("No file names stored. Manually upload the relevant PDFs to NotebookLM.")

    col_n1, col_n2 = st.columns(2)
    with col_n1:
        nlm_wc = st.number_input(
            "Word count target",
            min_value=0, max_value=5000,
            value=blueprint.get("word_count_target", 800) if blueprint else 800,
            step=100
        )
    with col_n2:
        nlm_style = st.text_input(
            "Style notes (optional)",
            placeholder="e.g. More analytical, less descriptive"
        )

    if st.button("⚙️ Compile NotebookLM Prompt", use_container_width=True, type="primary"):
        with st.spinner("Compiling..."):
            result = api.compile_notebooklm_prompt(
                chapter_id, subtopic_id,
                word_count=int(nlm_wc) if nlm_wc else None,
                style_notes=nlm_style or None
            )
        if result:
            st.session_state["nlm_prompt"] = result.get("prompt", "")
            st.session_state["nlm_meta"] = result.get("meta", {})

    if "nlm_prompt" in st.session_state and st.session_state["nlm_prompt"]:
        nlm_meta = st.session_state.get("nlm_meta", {})
        st.markdown("**NotebookLM Prompt — Copy and paste into NotebookLM:**")
        ui.prompt_output_box(st.session_state["nlm_prompt"], copy_key="copy_nlm")

        with st.expander("📋 What was included"):
            st.json({
                "task_md_approved": nlm_meta.get("task_md_approved"),
                "previous_section": nlm_meta.get("previous_section"),
                "suggested_pdf_uploads": nlm_meta.get("suggested_pdf_uploads"),
            })

    st.divider()

    # ── Save Consistency Summary ───────────────────────────────────────────────
    st.subheader("Save Consistency Summary")
    st.caption("After approving NotebookLM's draft, save what was argued here. This feeds into the next subtopic.")

    existing_summary = None
    for entry in chain:
        if entry.get("subtopic_id") == subtopic_id:
            existing_summary = entry
            break

    if existing_summary:
        st.success(f"Summary already saved for this subtopic.", icon="✅")
        with st.expander("View saved summary"):
            st.markdown(f"**{existing_summary.get('core_argument_made', '')}**")
            if existing_summary.get("key_terms_established"):
                st.caption(f"Terms: {', '.join(existing_summary['key_terms_established'])}")

    with st.form("consistency_form"):
        core_arg = st.text_area(
            "What was argued in this section? ★",
            height=120,
            value=existing_summary.get("core_argument_made", "") if existing_summary else "",
            placeholder="2–3 sentences. e.g. Established that pre-1947 male authors systematically constructed female characters as nationalist symbols using 'nationalist idealization' (Sharma Ch.2). This creates the baseline from which feminist writing departed.",
            help="Injected as 'Previous Section Context' in the next subtopic's prompts."
        )
        col1, col2 = st.columns(2)
        with col1:
            terms_raw = st.text_input(
                "Key Terms Established (comma-separated)",
                value=", ".join(existing_summary.get("key_terms_established", [])) if existing_summary else "",
                placeholder="nationalist idealization, representational gap"
            )
            sources_used_raw = st.text_input(
                "Sources Used",
                value=", ".join(existing_summary.get("sources_used", [])) if existing_summary else "",
                placeholder="Sharma Ch.2, Nair 1992"
            )
        with col2:
            bridge = st.text_area(
                "Bridge to Next Section (optional)",
                value=existing_summary.get("what_next_section_must_build_on", "") if existing_summary else "",
                height=100,
                placeholder="Next section should use 'nationalist idealization' as established baseline and show how feminist writers rejected it."
            )

        if st.form_submit_button("Save Summary", use_container_width=True, type="primary"):
            if not core_arg.strip():
                st.error("The argument summary is required.")
            else:
                data = {
                    "subtopic_number": subtopic["number"],
                    "subtopic_title": subtopic["title"],
                    "core_argument_made": core_arg,
                    "key_terms_established": [t.strip() for t in terms_raw.split(",") if t.strip()],
                    "sources_used": [s.strip() for s in sources_used_raw.split(",") if s.strip()],
                    "what_next_section_must_build_on": bridge or None,
                }
                result = api.save_consistency_summary(chapter_id, subtopic_id, data)
                if result:
                    ui.success("Summary saved. The next subtopic will inherit this context.")
                    st.rerun()
