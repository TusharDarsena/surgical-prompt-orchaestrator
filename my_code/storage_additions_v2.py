# ── ADD THESE FUNCTIONS TO YOUR EXISTING storage.py ──────────────────────────

import os
import json

# NOTE: adjust this to match your existing _data_dir() or DATA_DIR pattern
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ── Section Draft Storage ──────────────────────────────────────────────────────

def _draft_path(chapter_id: str, subtopic_id: str) -> str:
    draft_dir = os.path.join(DATA_DIR, "sections", chapter_id)
    os.makedirs(draft_dir, exist_ok=True)
    return os.path.join(draft_dir, f"{subtopic_id}_draft.json")


def read_section_draft(chapter_id: str, subtopic_id: str) -> dict | None:
    path = _draft_path(chapter_id, subtopic_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def write_section_draft(chapter_id: str, subtopic_id: str, data: dict) -> dict:
    path = _draft_path(chapter_id, subtopic_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def delete_section_draft(chapter_id: str, subtopic_id: str) -> bool:
    path = _draft_path(chapter_id, subtopic_id)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


# ── Drive Link Resolution ──────────────────────────────────────────────────────
# Used by the compiler to resolve source_ids in chapterization data to Drive links.
# The scan dictionary is keyed by thesis_name (level-4 folder name).
# Each entry has a "files" list of PDF filenames.
#
# We don't store Drive links directly — the local scan stores filenames only.
# Resolution returns the filename so the frontend can display it.
# When Drive links are added later, store them in the scan dict as
# { filename: drive_link } and update resolve_source_files accordingly.

def resolve_source_files(thesis_name: str, chapter_id_raw: str) -> list[dict]:
    """
    Given a thesis name (source_id from chapterization) and a raw chapter_id string,
    returns a list of matching file entries:
        [{ "file_name": "07_chapter 1.pdf", "drive_link": None or "https://..." }]

    chapter_id_raw may contain "AND" for multi-chapter sources, e.g.:
        "Chapter Two: Framing Life-narratives AND Chapter Five: The Feminist Subject"
    Each segment is resolved independently.

    Matching strategy:
        1. Split chapter_id_raw on " AND " to get individual chapter references
        2. For each reference, extract the chapter number word (one, two, three...)
           or digit and match against the numeric prefix of filenames (07_chapter 1 → 1)
        3. If no number match, fall back to partial filename string match on the reference
        4. Unmatched references are returned with file_name=None so the frontend
           can flag them without crashing
    """
    WORD_TO_NUM = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "introduction": "intro", "conclusion": "conclusion",
        "abstract": "abstract", "preface": "preface", "bibliography": "bibliography",
    }

    # Load scan dictionary
    scan = read_misc("drive_scan_result")
    if not scan:
        return []

    # Fuzzy-match thesis name against scan keys
    # The source_id in chapterization is 99% the same as the folder name
    thesis_entry = scan.get(thesis_name)
    if not thesis_entry:
        # Try case-insensitive match
        lower_name = thesis_name.lower()
        for key in scan:
            if key.lower() == lower_name:
                thesis_entry = scan[key]
                break

    if not thesis_entry:
        return []

    files = thesis_entry.get("files", [])
    # Build lookup: normalized chapter label → filename
    # e.g. "07_chapter 1.pdf" → key "1", "08_chapter 2.pdf" → key "2"
    file_map = {}
    for fname in files:
        lower_fname = fname.lower().replace(".pdf", "")
        # Extract numeric prefix (e.g. "07") and chapter number after "chapter "
        parts = lower_fname.split("_", 1)
        if len(parts) == 2:
            body = parts[1]  # e.g. "chapter 1", "preface", "bibliography"
            # Try "chapter N" pattern
            if "chapter" in body:
                num_part = body.replace("chapter", "").strip()
                file_map[num_part] = fname
            else:
                # Non-chapter files: preface, bibliography, abstract, etc.
                for keyword in WORD_TO_NUM:
                    if keyword in body:
                        file_map[WORD_TO_NUM[keyword]] = fname
                        break
                else:
                    file_map[body.strip()] = fname

    results = []
    # Split on " AND " to handle multi-chapter source_ids
    segments = [s.strip() for s in chapter_id_raw.split(" AND ")]

    for segment in segments:
        matched_file = None
        lower_seg = segment.lower()

        # Try to extract chapter number from segment
        for word, num in WORD_TO_NUM.items():
            if word in lower_seg:
                if num in file_map:
                    matched_file = file_map[num]
                    break

        # Also try bare digits in segment (e.g. "Chapter 2" → "2")
        if not matched_file:
            import re
            digits = re.findall(r'\b(\d+)\b', segment)
            for d in digits:
                if d in file_map:
                    matched_file = file_map[d]
                    break

        # Fallback: partial string match on filename body
        if not matched_file:
            for fname in files:
                if any(word in fname.lower() for word in lower_seg.split() if len(word) > 3):
                    matched_file = fname
                    break

        # Get drive link if stored (future: when Drive links are registered)
        drive_link = None
        if thesis_entry.get("drive_links") and matched_file:
            drive_link = thesis_entry["drive_links"].get(matched_file)

        results.append({
            "segment": segment,
            "file_name": matched_file,
            "drive_link": drive_link,
        })

    return results
