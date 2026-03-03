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
