"""
Source Resolver Service
=======================
Matches chapterization source_ids to source group records (primary) or the
local scan folder dict (legacy fallback) and resolves chapter references to
specific PDF filenames + Drive file IDs / links.

Primary path (new): uses storage.find_group_by_scan_key — Drive file IDs are
read directly from source records written by drive.py's register-links step.
No local scan dict required.

Fallback path (legacy): uses the scan dict (drive_scan_result.json) for groups
that pre-date the new architecture or have not been re-linked via register-links.

Used by compiler.py via storage.resolve_source_files() (re-exported).
"""

import re


# ── Public API ─────────────────────────────────────────────────────────────────────────────

def resolve_source_files(
    thesis_name: str,
    chapter_id_raw: str,
    scan: dict,
    thesis_id: str = "",
) -> list[dict]:
    """
    Given a thesis name (source_id from chapterization), a raw chapter_id string,
    and the scan dictionary, returns a list of resolved file entries:
        [
          {
            "segment":        "Chapter Two: ...",
            "file_name":      "08_chapter 2.pdf" or None,
            "drive_link":     "https://drive.google.com/..." or None,
            "drive_file_id":  "1A2B3C..." or None,
          }
        ]

    Resolution strategy:
      1. Primary (new): look up source group by scan_key in storage.
         Drive file IDs come directly from source records (no scan dict needed).
      2. Fallback (legacy): use the scan dict passed in.
         For groups that pre-date the new architecture.

    Handles:
      - AND / and / & splitting for multi-chapter references
      - Chapter number extraction: digits, word numbers, Roman numerals
      - Special chapter keywords: Introduction, Abstract, Preface, Conclusion, Bibliography etc.
      - Returns unresolved entries (file_name=None) instead of crashing on no match
    """
    # ── Step 1: split chapter_id_raw into individual chapter segments ───────────
    segments = _split_chapter_references(chapter_id_raw)

    # ── Step 2 (primary path): look up source group from storage ────────────────
    # Avoids depending on the scan dict for Drive file IDs.
    from services import storage as _storage
    group = _storage.find_group_by_scan_key(thesis_name, thesis_id)

    if group:
        group_sources = group.get("sources", [])
        files = [s["file_name"] for s in group_sources if s.get("file_name")]

        results = []
        for segment in segments:
            # Strategy 1-3: number/keyword/word-overlap match against filenames
            file_name = _match_chapter_to_file(segment, files)

            src = None
            if file_name:
                src = next(
                    (s for s in group_sources if s.get("file_name") == file_name),
                    None,
                )

            # Strategy 4: when chapterization uses raw chapter titles (not numbers),
            # match the segment directly against source.chapter_or_section / source.title.
            # This handles theses where chapter_id is e.g. "FEMINISM AND FEMINIST MOVEMENTS"
            # instead of "Chapter 2" — common when the chapterization JSON was generated
            # from a thesis with verbose chapter headings.
            if src is None:
                src = _match_segment_by_chapter_title(segment, group_sources)
                if src:
                    file_name = src.get("file_name")

            drive_file_id = None
            drive_link = None
            if src:
                drive_file_id = src.get("drive_file_id")
                if drive_file_id:
                    drive_link = f"https://drive.google.com/file/d/{drive_file_id}/view"
                elif src.get("drive_link"):
                    # Preserve any manually set drive_link on the source record
                    drive_link = src["drive_link"]
            results.append({
                "segment": segment,
                "file_name": file_name,
                "drive_link": drive_link,
                "drive_file_id": drive_file_id,
            })
        return results

    # ── Step 3 (legacy fallback): use scan dict ───────────────────────────────────
    # Runs when no source group exists yet (group not imported, or no scan_key set).
    if not scan:
        return []

    thesis_entry = _match_thesis_name(thesis_name, scan)
    if not thesis_entry:
        return []

    files = thesis_entry.get("files", [])

    # Pre-fetch the source group for Strategy 4 (chapter title matching).
    # The scan entry key may differ from thesis_name (e.g. different casing),
    # so look it up via find_group_by_scan_key with the matched scan key value.
    # This gives us chapter_or_section / title fields to match against.
    _fallback_group_sources: list = []
    try:
        _matched_scan_key = next(
            k for k in scan
            if scan[k] is thesis_entry  # identity compare — same dict object
        )
        _fb_group = _storage.find_group_by_scan_key(_matched_scan_key, thesis_id)
        if _fb_group:
            _fallback_group_sources = _fb_group.get("sources", [])
    except StopIteration:
        pass

    results = []
    for segment in segments:
        file_name = _match_chapter_to_file(segment, files)
        drive_link = None
        drive_file_id = None

        if file_name and thesis_entry.get("drive_links"):
            drive_link = thesis_entry["drive_links"].get(file_name)

        # Strategy 4 fallback: match by chapter_or_section / title on source records
        if drive_link is None and _fallback_group_sources:
            src4 = _match_segment_by_chapter_title(segment, _fallback_group_sources)
            if src4:
                file_name = src4.get("file_name") or file_name
                drive_file_id = src4.get("drive_file_id")
                if drive_file_id:
                    drive_link = f"https://drive.google.com/file/d/{drive_file_id}/view"
                elif src4.get("drive_link"):
                    drive_link = src4["drive_link"]
                elif file_name and thesis_entry.get("drive_links"):
                    drive_link = thesis_entry["drive_links"].get(file_name)

        results.append({
            "segment": segment,
            "file_name": file_name,
            "drive_link": drive_link,
            "drive_file_id": drive_file_id,
        })

    return results


# ── Chapter title → source record matching (Strategy 4) ──────────────────────

def _match_segment_by_chapter_title(segment: str, group_sources: list) -> dict | None:
    """
    Strategy 4 for source resolution: when the chapterization `chapter_id` is a
    raw chapter title (e.g. "FEMINISM AND FEMINIST MOVEMENTS") rather than a
    number ("Chapter 2"), match it directly against the `chapter_or_section`
    and `title` fields stored on each source record.

    Tries in order:
      1. Exact case-insensitive match against chapter_or_section
      2. Exact case-insensitive match against title
      3. Slugified match against chapter_or_section
      4. Slugified match against title
    Returns the matching source dict, or None.
    """
    import re as _re

    def _norm(s: str) -> str:
        """Lowercase and collapse whitespace/punctuation to single spaces."""
        s = _re.sub(r'[^a-z0-9]', ' ', s.lower())
        return _re.sub(r'\s+', ' ', s).strip()

    seg_norm = _norm(segment)
    if not seg_norm:
        return None

    # Pass 1 & 2: normalised exact match
    for src in group_sources:
        for field in ("chapter_or_section", "title"):
            val = src.get(field, "") or ""
            if val and _norm(val) == seg_norm:
                return src

    # Pass 3 & 4: one is a prefix of the other (handles truncated titles)
    for src in group_sources:
        for field in ("chapter_or_section", "title"):
            val = src.get(field, "") or ""
            if not val:
                continue
            val_norm = _norm(val)
            if val_norm.startswith(seg_norm) or seg_norm.startswith(val_norm):
                return src

    return None


# ── Thesis name matching ───────────────────────────────────────────────────────

import re
import os
import difflib

def _slugify(text: str) -> str:
    # Basic slugification: lower case, replace non-alphanumeric with underscore
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    # Collapse multiple underscores
    text = re.sub(r'_+', '_', text)
    return text.lower().strip('_')

def _match_thesis_name(source_id: str, scan: dict) -> dict | None:
    """
    Matches source_id (from chapterization) to a key in the scan dictionary.
    Tries in order:
      1. Exact match — always hits when chapterization source_ids match folder names exactly
      2. Case-insensitive fallback — protects against accidental casing differences
      3. Slugified match — handles standard formatting mismatches
      4. Prefix match — handles truncated folder names
      5. Fuzzy match — handles minor typos like 'woman' vs 'women' using difflib
    Returns the scan entry dict, or None if no match found.
    """
    # 1. Exact
    if source_id in scan:
        return scan[source_id]

    # 2. Case-insensitive
    lower_id = source_id.lower()
    for k in scan:
        if k.lower() == lower_id:
            return scan[k]
            
    # 3. Slugified match
    slug_id = _slugify(source_id)
    for k in scan:
        if _slugify(k) == slug_id:
            return scan[k]
            
    # 4. Partial substring prefix match (for truncated names)
    for k in scan:
        if _slugify(k).startswith(slug_id):
            return scan[k]
    for k in scan:
        if slug_id.startswith(_slugify(k)):
            return scan[k]

    # 5. Difflib fuzzy matching for minor typos (like "woman" vs "women").
    # Cutoff 0.85 is intentionally tight: loose matching risks cross-thesis false
    # positives (e.g. a Bharti Devi source_id matching a Jitendra Kumar entry).
    # If this step fails, the resolver returns None and the compiler emits a
    # warning — the human sees it and can investigate via check_source_ids.
    scan_slugs = {_slugify(k): k for k in scan}
    matches = difflib.get_close_matches(slug_id, scan_slugs.keys(), n=1, cutoff=0.85)
    if matches:
        return scan[scan_slugs[matches[0]]]

    return None


# ── Chapter reference splitting ────────────────────────────────────────────────

def _split_chapter_references(chapter_id_raw: str) -> list[str]:
    """
    Splits a chapter_id string into individual chapter references.

    Handles:
      " AND " (uppercase) — always split
      " and " (lowercase) — split only if both sides look like chapter references
      " & "              — split only if both sides look like chapter references
      "Chapters 2 and 5" — split on "and" between numbers
      "Chapter 2, Chapter 5" — split on comma between chapter references

    Does NOT split on "and" inside a title like
    "Framing Life-narratives as Performance and Agency"
    """
    raw = chapter_id_raw.strip()

    # Zero pass: "Chapters N and M" / "Chapters N & M" — plural with bare numbers/words
    m = re.match(
        r'chapters?\s+(\w+)\s+(?:and|&)\s+(\w+)\s*$',
        raw, re.IGNORECASE
    )
    if m:
        return [f"Chapter {m.group(1)}", f"Chapter {m.group(2)}"]

    # First pass: split on uppercase AND only when both sides look like chapter refs.
    # Unconditional splitting caused false positives on chapter titles like
    # "CHAPTER III ... EMERGENCY AND HUMAN PSYCHE" where AND is part of the title.
    if ' AND ' in raw:
        parts = [p.strip() for p in raw.split(' AND ') if p.strip()]
        if len(parts) > 1 and _looks_like_chapter_ref(parts[0]) and _looks_like_chapter_ref(parts[-1]):
            return parts

    # Second pass: split on comma + "Chapter" pattern
    # e.g. "Chapter Two: Title One, Chapter Five: Title Two"
    comma_split = re.split(r',\s*(?=(?:chapter|ch\.?|section|part)\s)', raw, flags=re.IGNORECASE)
    if len(comma_split) > 1:
        return [p.strip() for p in comma_split if p.strip()]

    # Third pass: split on " and " or " & " only when flanked by chapter indicators
    and_pattern = re.compile(
        r'(.+?)\s+(?:and|&)\s+(.+)',
        re.IGNORECASE
    )
    m = and_pattern.match(raw)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        if _looks_like_chapter_ref(left) and _looks_like_chapter_ref(right):
            return [left, right]

    # No split — return as single segment
    return [raw]


def _looks_like_chapter_ref(text: str) -> bool:
    """
    Returns True if text looks like a chapter reference rather than
    a fragment of a title.
    """
    t = text.strip().lower()

    # Starts with chapter/section/part indicator
    if re.match(r'^(?:chapter|ch\.?|section|sec\.?|part)\b', t):
        return True

    # Is a standalone number or Roman numeral
    if re.match(r'^[ivxlc\d]+$', t):
        return True

    # Is a known special chapter keyword
    keywords = {
        'introduction', 'intro', 'abstract', 'preface', 'conclusion',
        'bibliography', 'references', 'appendix', 'acknowledgement',
        'acknowledgments', 'contents', 'declaration', 'certificate'
    }
    if t in keywords:
        return True

    return False


# ── Chapter-to-file matching ───────────────────────────────────────────────────

# Word numbers → digit
_WORD_TO_NUM = {
    'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
    'eleven': '11', 'twelve': '12', 'thirteen': '13', 'fourteen': '14',
    'fifteen': '15',
}

# Roman numerals → digit (whole word match only, checked before word number)
_ROMAN_TO_NUM = {
    'xii': '12', 'xi': '11', 'x': '10',
    'ix': '9', 'viii': '8', 'vii': '7', 'vi': '6',
    'v': '5', 'iv': '4', 'iii': '3', 'ii': '2', 'i': '1',
}

# Special keyword synonyms → canonical keyword used in filename matching
_KEYWORD_MAP = {
    'introduction': 'introduction',
    'intro': 'introduction',
    'introductory': 'introduction',
    'abstract': 'abstract',
    'preface': 'preface',
    'conclusion': 'conclusion',
    'concluding': 'conclusion',
    'bibliography': 'bibliography',
    'references': 'bibliography',
    'works cited': 'bibliography',
    'acknowledgement': 'acknowledgement',
    'acknowledgements': 'acknowledgement',
    'acknowledgment': 'acknowledgement',
    'acknowledgments': 'acknowledgement',
    'contents': 'contents',
    'table of contents': 'contents',
    'toc': 'contents',
    'appendix': 'appendix',
    'declaration': 'declaration',
    'certificate': 'certificate',
    'title page': 'title page',
    'title': 'title page',
}


def _match_chapter_to_file(segment: str, files: list[str]) -> str | None:
    """
    Matches one chapter segment to a filename from the file list.

    Strategy (in order):
      1. Extract chapter number → match against "chapter N" in filename body
      2. Extract keyword (introduction, conclusion, etc.) → match in filename body
      3. Normalized partial match — significant words from segment appear in filename
      4. Return None if no match
    """
    if not files:
        return None

    # Build parsed file list once
    parsed_files = [_parse_filename(f) for f in files]

    seg_lower = segment.strip().lower()

    # ── Strategy 1: extract chapter number from segment ───────────────────────
    chapter_num = _extract_chapter_number(seg_lower)

    if chapter_num:
        for pf in parsed_files:
            if pf['number'] == chapter_num:
                return pf['original']

    # ── Strategy 2: extract keyword from segment ──────────────────────────────
    keyword = _extract_keyword(seg_lower)

    if keyword:
        for pf in parsed_files:
            if pf['keyword'] == keyword:
                return pf['original']

        # Special case: "Introduction" often lives in chapter 1
        if keyword == 'introduction':
            for pf in parsed_files:
                if pf['number'] == '1':
                    return pf['original']

    # ── Strategy 3: normalized partial match ──────────────────────────────────
    seg_words = set(
        w for w in re.findall(r'[a-z]{5,}', seg_lower)
        if w not in {'chapter', 'section', 'selected', 'novels', 'about', 'which', 'their'}
    )
    if seg_words:
        for pf in parsed_files:
            body_words = set(re.findall(r'[a-z]{5,}', pf['body']))
            if seg_words & body_words:
                return pf['original']

    return None


def _extract_chapter_number(text: str) -> str | None:
    """
    Extracts a chapter number from a segment string.
    Returns string digit e.g. '2', or None.

    Handles: "chapter 2", "chapter two", "ch. 3", "section 4", "part v",
             standalone "2", "II", "chapter1"
    """
    # Pattern: chapter/section/part + digit
    m = re.search(
        r'(?:chapter|ch\.?|section|sec\.?|part)\s*(\d+)',
        text, re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Try word number after chapter indicator
    m = re.search(
        r'(?:chapter|ch\.?|section|sec\.?|part)\s*(' + '|'.join(_WORD_TO_NUM.keys()) + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return _WORD_TO_NUM[m.group(1).lower()]

    # Try Roman numeral after chapter indicator
    roman_pattern = r'(?:chapter|ch\.?|section|sec\.?|part)\s*(' + '|'.join(_ROMAN_TO_NUM.keys()) + r')\b'
    m = re.search(roman_pattern, text, re.IGNORECASE)
    if m:
        return _ROMAN_TO_NUM[m.group(1).lower()]

    # Standalone digit
    m = re.fullmatch(r'\s*(\d+)\s*', text)
    if m:
        return m.group(1)

    # Standalone Roman numeral
    for roman, num in _ROMAN_TO_NUM.items():
        if re.fullmatch(r'\s*' + roman + r'\s*', text, re.IGNORECASE):
            return num

    return None


def _extract_keyword(text: str) -> str | None:
    """
    Extracts a special chapter keyword from a segment string.
    Returns canonical keyword string or None.
    """
    t = text.strip().lower()

    # Multi-word first (longer matches take priority)
    for phrase in sorted(_KEYWORD_MAP.keys(), key=len, reverse=True):
        if phrase in t:
            return _KEYWORD_MAP[phrase]

    return None


def _parse_filename(filename: str) -> dict:
    """
    Parses a filename like "08_chapter 2.pdf" or "05_preface.pdf" into:
    {
        original: "08_chapter 2.pdf",
        body: "chapter 2",          # after stripping prefix and extension
        number: "2" or None,        # chapter number if present
        keyword: "preface" or None, # canonical keyword if present
    }
    """
    original = filename
    # Strip extension
    base = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
    # Strip leading NN_ prefix
    body = re.sub(r'^\d+_', '', base).strip().lower()

    number = None
    keyword = None

    # Try to extract chapter number from body
    m = re.search(r'(?:chapter|chap\.?|ch\.?|section|part)\s*-?\s*(\d+)', body)
    if m:
        number = m.group(1)
    else:
        m = re.fullmatch(r'(\d+)', body.strip())
        if m:
            number = m.group(1)

    # Try keyword
    if not number:
        for phrase in sorted(_KEYWORD_MAP.keys(), key=len, reverse=True):
            if phrase in body:
                keyword = _KEYWORD_MAP[phrase]
                break

    return {
        'original': original,
        'body': body,
        'number': number,
        'keyword': keyword,
    }