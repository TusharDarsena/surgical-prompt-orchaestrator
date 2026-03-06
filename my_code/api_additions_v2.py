# ── ADD THESE FUNCTIONS TO YOUR EXISTING api.py ───────────────────────────────


def get_section_draft(chapter_id: str, subtopic_id: str) -> dict | None:
    """
    GET /sections/{chapter_id}/{subtopic_id}/draft
    Returns the saved draft for a subtopic, or None if none exists.
    404 is treated as None — not an error.
    """
    try:
        r = requests.get(f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        st.error(f"Could not load draft: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def save_section_draft(chapter_id: str, subtopic_id: str, text: str) -> dict | None:
    """
    POST /sections/{chapter_id}/{subtopic_id}/draft
    Saves or overwrites the draft for a subtopic.
    """
    try:
        r = requests.post(
            f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft",
            json={"text": text}
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Could not save draft: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None


def delete_section_draft(chapter_id: str, subtopic_id: str) -> bool:
    """
    DELETE /sections/{chapter_id}/{subtopic_id}/draft
    """
    try:
        r = requests.delete(f"{BASE_URL}/sections/{chapter_id}/{subtopic_id}/draft")
        return r.status_code == 200
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return False


# ── UPDATE your existing compile_notebooklm_prompt() to match this signature ──
# The old version required task.md. The new endpoint no longer does.
# Replace the existing function body with this:

def compile_notebooklm_prompt(
    chapter_id: str,
    subtopic_id: str,
    word_count: int | None = None,
    style_notes: str | None = None,
) -> dict | None:
    """
    GET /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}
    Builds prompt directly from chapterization data.
    Returns prompt + meta.required_sources with resolved filenames/links.
    """
    try:
        params = {}
        if word_count:
            params["word_count"] = word_count
        if style_notes:
            params["academic_style_notes"] = style_notes
        r = requests.get(
            f"{BASE_URL}/compile/notebooklm-prompt/{chapter_id}/{subtopic_id}",
            params=params
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Compile failed: {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        st.error(f"Could not reach backend: {e}")
        return None
