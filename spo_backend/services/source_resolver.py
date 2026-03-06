"""
Source Resolver Service
=======================
Matches chapterization source_ids to local scan folder names and
resolves chapter references to specific PDF filenames + Drive links.

Used by compiler.py via storage.resolve_source_files() (re-exported).
"""

import re


# ── Public API ─────────────────────────────────────────────────────────────────

def resolve_source_files(thesis_name: str, chapter_id_raw: str, scan: dict) -> list[dict]:
    """
    Given a thesis name (source_id from chapterization), a raw chapter_id string,
    and the scan dictionary, returns a list of resolved file entries:
        [{ "segment": "Chapter Two: ...", "file_name": "08_chapter 2.pdf", "drive_link": "https://..." or None }]

    Handles:
      - Thesis name normalization (strips author/year parentheticals, punctuation, case, underscores)
      - Prefix fallback for truncated folder names
      - AND / and / & splitting for multi-chapter references
      - Chapter number extraction: digits, word numbers, Roman numerals
      - Special chapter keywords: Introduction, Abstract, Preface, Conclusion, Bibliography etc.
      - Returns unresolved entries (file_name=None) instead of crashing on no match
    """
    if not scan:
        return []

    # ── Step 1: match thesis name to scan key ─────────────────────────────────
    thesis_entry = _match_thesis_name(thesis_name, scan)
    if not thesis_entry:
        return []

    files = thesis_entry.get("files", [])

    # ── Step 2: split chapter_id_raw into individual chapter segments ─────────
    segments = _split_chapter_references(chapter_id_raw)

    # ── Step 3: resolve each segment to a filename ────────────────────────────
    results = []
    for segment in segments:
        file_name = _match_chapter_to_file(segment, files)
        drive_link = None
        if file_name and thesis_entry.get("drive_links"):
            drive_link = thesis_entry["drive_links"].get(file_name)
        results.append({
            "segment": segment,
            "file_name": file_name,
            "drive_link": drive_link,
        })

    return results


# ── Thesis name matching ───────────────────────────────────────────────────────

def _match_thesis_name(source_id: str, scan: dict) -> dict | None:
    """
    Matches source_id (from chapterization) to a key in the scan dictionary.
    Tries in order:
      1. Exact match
      2. Case-insensitive exact match
      3. Normalized match (strip parentheticals, punctuation, underscores, lowercase)
      4. Prefix match — normalized folder name is prefix of normalized source_id or vice versa
    Returns the scan entry dict, or None if no match found.
    """
    # Build normalized versions of all scan keys once
    norm_map = {_normalize_thesis_name(k): k for k in scan}

    # 1. Exact
    if source_id in scan:
        return scan[source_id]

    # 2. Case-insensitive exact
    lower_id = source_id.lower()
    for k in scan:
        if k.lower() == lower_id:
            return scan[k]

    # 3. Normalized match
    norm_source = _normalize_thesis_name(source_id)
    if norm_source in norm_map:
        return scan[norm_map[norm_source]]

    # 4. Prefix match — handles truncated folder names
    # e.g. folder "...Cry_ the P" normalized matches start of normalized source_id
    # Require minimum 20 chars to avoid false positives on short common words
    MIN_PREFIX = 20
    for norm_key, original_key in norm_map.items():
        short, long = (
            (norm_key, norm_source) if len(norm_key) <= len(norm_source)
            else (norm_source, norm_key)
        )
        if len(short) >= MIN_PREFIX and long.startswith(short):
            return scan[original_key]

    return None


def _normalize_thesis_name(name: str) -> str:
    """
    Normalizes a thesis name for matching.
    Steps:
      1. Strip trailing parenthetical (author, year) — e.g. (Puhan, 2018), (author unlisted)
      2. Replace underscores with spaces
      3. Replace punctuation chars with spaces
      4. Collapse multiple spaces
      5. Lowercase and strip
    """
    s = name.strip()

    # Strip trailing parentheticals like (Puhan, 2018) or (author unlisted) or (2019)
    while True:
        stripped = re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()
        if stripped == s:
            break
        s = stripped

    # Replace underscores with spaces
    s = s.replace('_', ' ')

    # Replace punctuation with spaces
    s = re.sub(r"[:\-,.'\"''\u2018\u2019\u201c\u201d/\\()\[\]{}]", ' ', s)

    # Collapse whitespace and lowercase
    s = re.sub(r'\s+', ' ', s).strip().lower()

    return s


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

    # First pass: always split on uppercase AND (explicit multi-chapter marker)
    if ' AND ' in raw:
        parts = [p.strip() for p in raw.split(' AND ') if p.strip()]
        if len(parts) > 1:
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
             standalone "2", "II"
    """
    # Pattern: chapter/section/part + digit
    m = re.search(
        r'(?:chapter|ch\.?|section|sec\.?|part)\s+(\d+)',
        text, re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Try word number after chapter indicator
    m = re.search(
        r'(?:chapter|ch\.?|section|sec\.?|part)\s+(' + '|'.join(_WORD_TO_NUM.keys()) + r')\b',
        text, re.IGNORECASE
    )
    if m:
        return _WORD_TO_NUM[m.group(1).lower()]

    # Try Roman numeral after chapter indicator
    roman_pattern = r'(?:chapter|ch\.?|section|sec\.?|part)\s+(' + '|'.join(_ROMAN_TO_NUM.keys()) + r')\b'
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
    m = re.search(r'chapter\s+(\d+)', body)
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
