"""
Shared UI helpers used across pages.
"""

import streamlit as st
import pyperclip


def page_header(title: str, subtitle: str = ""):
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    st.divider()


def success(msg: str):
    st.success(msg, icon="✅")


def warn(msg: str):
    st.warning(msg, icon="⚠️")


def info(msg: str):
    st.info(msg, icon="ℹ️")


def copy_button(text: str, label: str = "📋 Copy to Clipboard", key: str = None):
    """Renders a button that copies text to clipboard."""
    if st.button(label, key=key, use_container_width=True, type="primary"):
        try:
            pyperclip.copy(text)
            st.toast("Copied to clipboard!", icon="✅")
        except Exception:
            st.toast("Auto-copy failed — select and copy manually.", icon="⚠️")


def prompt_output_box(prompt_text: str, copy_key: str = "copy_prompt"):
    """Renders the compiled prompt with copy button."""
    copy_button(prompt_text, key=copy_key)
    st.code(prompt_text, language=None)


def status_badge(label: str, ok: bool):
    color = "green" if ok else "red"
    icon = "✅" if ok else "❌"
    st.markdown(f":{color}[{icon} {label}]")


def subtopic_selector(chapters: list) -> tuple[str | None, dict | None, dict | None]:
    """
    Renders chapter → subtopic selectors.
    Returns (chapter_id, chapter_dict, subtopic_dict).
    """
    if not chapters:
        st.warning("No chapters found. Add chapters in **Thesis Setup** first.")
        return None, None, None

    chapter_options = {f"Ch.{c['number']} — {c['title']}": c for c in chapters}
    selected_ch_label = st.selectbox("Chapter", list(chapter_options.keys()))
    chapter = chapter_options[selected_ch_label]

    subtopics = chapter.get("subtopics", [])
    if not subtopics:
        st.warning(f"No subtopics in this chapter. Add them in **Thesis Setup**.")
        return chapter["chapter_id"], chapter, None

    sub_options = {f"{s['number']} — {s['title']}": s for s in subtopics}
    selected_sub_label = st.selectbox("Subtopic", list(sub_options.keys()))
    subtopic = sub_options[selected_sub_label]

    return chapter["chapter_id"], chapter, subtopic


def warnings_box(warnings: list[str]):
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} warning(s) — review before using prompt", expanded=False):
            for w in warnings:
                st.warning(w)


def tags_input(label: str, help: str, key: str, default: list = None) -> list[str]:
    """Comma-separated tags input that returns a list."""
    default_str = ", ".join(default) if default else ""
    raw = st.text_input(label, value=default_str, help=help, key=key)
    return [t.strip() for t in raw.split(",") if t.strip()]


def validate_json_schema(data: dict, required_fields: list[str]) -> list[str]:
    """
    Returns a list of required fields missing from *data*.
    Empty list means the schema is valid.

    Usage (any upload form)::

        missing = ui.validate_json_schema(uploaded_data, ["number", "title", "goal"])
        if missing:
            st.error(f"Missing: {missing}")
        else:
            # proceed
    """
    return [f for f in required_fields if not data.get(f)]


def render_outline_import_form(key_suffix: str) -> None:
    """
    Renders the complete freeform-outline → chapterization import form.

    Accepts the user's own chapter outline JSON (the ``chapters.json`` style:
    a dict of section numbers → title strings or nested dicts) and converts it
    into the structured payload expected by ``POST /import/chapterization/{id}``.

    Parameters
    ----------
    key_suffix:
        A unique string appended to all widget keys so the form can be embedded
        multiple times on the same page without key collisions.
    """
    import api  # local import to avoid circular dependency with ui module

    st.caption(
        "Upload your own chapter outline JSON (e.g. `chapters.json`). "
        "SPO flattens all entries into a subtopic list. "
        "Add the chapter goal and arc here before importing."
    )
    st.info(
        "**Expected format:** keys are section numbers (`\"1.1\"`, `\"1.2\"` …) "
        "and values are either a title string or `{\"title\": …, \"subtopics\": {…}}`. "
        "Entries are extracted recursively in document order.",
        icon="ℹ️",
    )

    ch_id = st.text_input(
        "Target chapter_id",
        placeholder="chapter_01",
        key=f"ch_id_outline_{key_suffix}",
        help="Must be unique per chapter — e.g. chapter_01, chapter_02.",
    )

    uploaded = st.file_uploader(
        "Upload outline JSON", type="json", key=f"ch_outline_upload_{key_suffix}"
    )

    if not (uploaded and ch_id):
        return

    try:
        raw = __import__("json").load(uploaded)
    except ValueError as e:
        st.error(f"Invalid JSON: {e}")
        return

    # Unwrap chapter-name wrapper (e.g. {"Chapter 1: ...": {...}})
    if raw and not any(k[0].isdigit() for k in raw.keys()):
        first_key = next(iter(raw))
        outline_data = raw[first_key]
        detected_title = first_key
    else:
        outline_data = raw
        detected_title = None

    subtopics = list(flatten_chapter_outline(outline_data))

    st.success(f"Detected **{len(subtopics)} subtopics** from outline.")
    if detected_title:
        st.caption(f"Chapter title detected from file: *{detected_title}*")

    with st.expander("Subtopics extracted — review before importing", expanded=True):
        for s in subtopics:
            st.markdown(f"- `{s['number']}` {s['title']}")

    st.divider()
    st.markdown("**Fill in the required fields before importing:**")

    with st.form(f"outline_import_form_{key_suffix}"):
        col1, col2 = st.columns([3, 1])
        with col1:
            title = st.text_input(
                "Chapter Title", value=detected_title or "", placeholder="Introduction"
            )
        with col2:
            num = st.number_input("Chapter Number", min_value=1, max_value=20, value=1, step=1)

        goal = st.text_area(
            "Chapter Goal ★",
            height=100,
            placeholder=(
                "What must this chapter prove? How does it serve the thesis argument? "
                "2–3 sentences. Injected into every Architect prompt."
            ),
        )
        arc = st.text_area(
            "Chapter Arc ★",
            height=160,
            placeholder=(
                "150–200 words. How all subtopics connect argumentatively — what each establishes, "
                "how they build on each other, what the chapter achieves by the end.\n\n"
                "Tip: paste your outline into Claude with "
                "prompts/generate_chapterization_json.txt to generate this."
            ),
        )

        if st.form_submit_button("Import Chapter", use_container_width=True, type="primary"):
            if not title or not goal:
                st.error("Chapter Title and Goal are required.")
            else:
                if len(arc.split()) < 50:
                    st.warning(
                        "Arc is short — recommend 150–200 words. "
                        "You can edit it later via the ✏️ button."
                    )
                payload = {
                    "number": int(num),
                    "title": title,
                    "goal": goal,
                    "chapter_arc": arc or "",
                    "subtopics": [
                        {
                            "number": s["number"],
                            "title": s["title"],
                            "goal": "To be defined — edit after import.",
                            "position_in_argument": None,
                        }
                        for s in subtopics
                    ],
                }
                result = api.post(f"/import/chapterization/{ch_id}", payload)
                if result:
                    api.list_chapters.clear()
                    success(
                        f"Imported: Chapter {num} — {title}. "
                        f"{result.get('subtopics_created')} subtopics created. "
                        "Edit subtopic goals via the ✏️ Edit button."
                    )
                    st.rerun()


def flatten_chapter_outline(outline: dict):
    """
    Generator that recursively flattens a freeform chapter outline dict into
    ``{"number": str, "title": str}`` dicts.

    Handles two value shapes:
      - Plain string:   ``{"1.1": "Some title"}``
      - Nested object:  ``{"1.2": {"title": "...", "subtopics": {"1.2.1": "..."}}}``

    Both the parent entry and its children are yielded (depth-first).
    """
    for number, value in outline.items():
        if isinstance(value, str):
            yield {"number": number, "title": value}
        elif isinstance(value, dict):
            title = value.get("title") or value.get("name") or number
            yield {"number": number, "title": title}
            nested = value.get("subtopics") or value.get("children") or {}
            if isinstance(nested, dict):
                yield from flatten_chapter_outline(nested)
