"""
fix_source_ids.py — Interactive CLI to fix source_id mismatches
================================================================
Reads chapterization JSONs, compares source_ids against drive_scan_result.json
keys using the same resolver the backend uses, and lets you interactively fix
any mismatches. Writes corrected JSON directly (with .bak backup).

Usage:
    python scripts/fix_source_ids.py --thesis-id t_1773774349746
"""

import sys
import os
import json
import shutil
import argparse
from pathlib import Path

# Add project root to sys.path so we can import the resolver
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "spo_backend"))

from services.source_resolver import _match_thesis_name  # noqa: E402


# ── Config ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("SPO_DATA_DIR", Path.home() / "spo_data"))


def _chapters_dir(thesis_id: str) -> Path:
    if thesis_id:
        return DATA_DIR / "theses" / thesis_id / "thesis_context" / "chapters"
    return DATA_DIR / "thesis_context" / "chapters"


def _scan_path() -> Path:
    return DATA_DIR / "misc" / "drive_scan_result.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_scan_keys() -> dict:
    """Load drive_scan_result.json and return the full dict."""
    path = _scan_path()
    if not path.exists():
        print(f"ERROR: {path} not found. Run a drive scan first.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_chapters(thesis_id: str) -> list[tuple[Path, dict]]:
    """Return list of (file_path, chapter_dict) for all chapter JSONs."""
    cdir = _chapters_dir(thesis_id)
    if not cdir.exists():
        print(f"ERROR: {cdir} not found.")
        sys.exit(1)
    results = []
    for p in sorted(cdir.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            results.append((p, json.load(f)))
    return results


def extract_all_source_ids(chapter: dict) -> list[str]:
    """Extract every unique source_id from subtopics + reserved sources."""
    ids = set()
    for sub in chapter.get("subtopics", []):
        for src in sub.get("source_ids", []):
            sid = src.get("source_id", "").strip()
            if sid:
                ids.add(sid)
    for reserved in chapter.get("sources_reserved_for_later_chapters", []):
        sid = reserved.get("source_id", "").strip()
        if sid:
            ids.add(sid)
    return sorted(ids)


def find_subtopics_using(chapter: dict, source_id: str) -> list[str]:
    """Return list of subtopic numbers that use this source_id."""
    result = []
    for sub in chapter.get("subtopics", []):
        for src in sub.get("source_ids", []):
            if src.get("source_id", "").strip() == source_id:
                result.append(sub.get("number", "?"))
                break
    # Check reserved
    for reserved in chapter.get("sources_reserved_for_later_chapters", []):
        if reserved.get("source_id", "").strip() == source_id:
            result.append("(reserved)")
            break
    return result


def replace_source_id(chapter: dict, old_id: str, new_id: str) -> int:
    """Replace all occurrences of old_id with new_id in the chapter. Returns count."""
    count = 0
    for sub in chapter.get("subtopics", []):
        for src in sub.get("source_ids", []):
            if src.get("source_id", "").strip() == old_id:
                src["source_id"] = new_id
                count += 1
    for reserved in chapter.get("sources_reserved_for_later_chapters", []):
        if reserved.get("source_id", "").strip() == old_id:
            reserved["source_id"] = new_id
            count += 1
    return count


def prompt_user(source_id: str, scan_keys: list[str], subtopics: list[str]) -> str | None:
    """Interactive prompt. Returns the chosen scan key, or None to skip."""
    print(f"\n{'='*70}")
    print(f"  MISMATCH: \"{source_id}\"")
    print(f"  Used in: {', '.join(subtopics)}")
    print(f"{'='*70}")
    print()
    for i, key in enumerate(scan_keys, 1):
        print(f"  [{i}] {key}")
    print(f"  [{len(scan_keys)+1}] Skip")
    print(f"  [{len(scan_keys)+2}] Enter manually")
    print()

    while True:
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            sys.exit(0)

        if not choice:
            continue

        try:
            idx = int(choice)
        except ValueError:
            print("  Enter a number.")
            continue

        if idx == len(scan_keys) + 1:
            return None  # Skip
        elif idx == len(scan_keys) + 2:
            manual = input("  Paste exact scan key: ").strip()
            if manual:
                return manual
            print("  Empty — skipping.")
            return None
        elif 1 <= idx <= len(scan_keys):
            return scan_keys[idx - 1]
        else:
            print(f"  Enter 1–{len(scan_keys)+2}.")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fix source_id mismatches in chapterization JSONs")
    parser.add_argument("--thesis-id", default="", help="Thesis ID (e.g. t_1773774349746)")
    args = parser.parse_args()

    scan = load_scan_keys()
    scan_key_list = sorted(scan.keys())
    chapters = load_chapters(args.thesis_id)

    if not chapters:
        print("No chapter files found.")
        return

    print(f"\nLoaded {len(chapters)} chapter(s), {len(scan_key_list)} scan keys.")

    # Mapping memory: wrong_name → correct_name (persists across chapters)
    memory: dict[str, str | None] = {}
    total_fixes = 0
    total_skipped = 0

    for filepath, chapter in chapters:
        ch_id = chapter.get("chapter_id", filepath.stem)
        source_ids = extract_all_source_ids(chapter)
        chapter_modified = False

        for sid in source_ids:
            # Already resolved by the backend's matcher? Skip.
            if _match_thesis_name(sid, scan) is not None:
                continue

            # Already resolved by memory?
            if sid in memory:
                if memory[sid] is not None:
                    count = replace_source_id(chapter, sid, memory[sid])
                    print(f"  [auto] {ch_id}: \"{sid[:50]}...\" → \"{memory[sid][:50]}...\" ({count}x)")
                    total_fixes += count
                    chapter_modified = True
                else:
                    total_skipped += 1
                continue

            # Interactive prompt
            subtopics = find_subtopics_using(chapter, sid)
            chosen = prompt_user(sid, scan_key_list, subtopics)
            memory[sid] = chosen

            if chosen is not None:
                count = replace_source_id(chapter, sid, chosen)
                print(f"  ✓ Mapped ({count}x)")
                total_fixes += count
                chapter_modified = True
            else:
                print("  — Skipped")
                total_skipped += 1

        # Write back if modified
        if chapter_modified:
            # Backup
            bak_path = filepath.with_suffix(".json.bak")
            shutil.copy2(filepath, bak_path)
            print(f"  Backup: {bak_path.name}")

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(chapter, f, indent=2, ensure_ascii=False)
            print(f"  ✓ Saved {filepath.name}")

    print(f"\n{'='*70}")
    print(f"  Done. {total_fixes} fix(es) applied, {total_skipped} skipped.")
    if memory:
        applied = {k: v for k, v in memory.items() if v is not None}
        if applied:
            print(f"  Mappings used: {len(applied)}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
