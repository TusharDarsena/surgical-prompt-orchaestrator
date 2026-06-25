"""
fix_all_scan_keys.py
====================
One-time repair script that:
  1. Sets the correct scan_key on every source group in BOTH theses by
     fuzzy-matching group titles against the drive_scan_result keys.
  2. Directly injects drive_file_id into source records for ALL groups whose
     source filenames can be matched to the drive_links dict in the scan.

Run from the project root:
    python scripts/fix_all_scan_keys.py

The underlying bug was that /drive/register-links was called without
thesis_id, so find_group_by_scan_key always searched the root
source_groups/ (empty) instead of the thesis-scoped directories.
This script repairs the damage for all theses by directly writing
drive_file_ids from the scan dict into the source JSON files.
"""

import json
import os
import re
import difflib
from pathlib import Path

DATA_DIR = Path(os.environ.get("SPO_DATA_DIR", Path.home() / "spo_data"))


# ── helpers ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def match_scan_key(title: str, scan_keys: list) -> str:
    """Return the best-matching scan key for a group title, or None."""
    slug_title = slugify(title)
    slug_keys = {slugify(k): k for k in scan_keys}

    # 1. Exact slugified match
    if slug_title in slug_keys:
        return slug_keys[slug_title]

    # 2. One is prefix of the other (handles truncated Drive folder names)
    for slug, orig in slug_keys.items():
        if slug.startswith(slug_title) or slug_title.startswith(slug):
            return orig

    # 3. Difflib fuzzy (cutoff 0.75 — loose enough for minor differences)
    matches = difflib.get_close_matches(slug_title, slug_keys.keys(), n=1, cutoff=0.75)
    if matches:
        return slug_keys[matches[0]]

    return None


def all_thesis_ids():
    """Return [""] for the root thesis + all t_... named theses."""
    ids = [""]
    theses_root = DATA_DIR / "theses"
    if theses_root.exists():
        ids += [d.name for d in sorted(theses_root.iterdir()) if d.is_dir()]
    return ids


def groups_dir(thesis_id: str) -> Path:
    if thesis_id:
        return DATA_DIR / "theses" / thesis_id / "source_groups"
    return DATA_DIR / "source_groups"


def sources_dir(group_path: Path) -> Path:
    return group_path / "sources"


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    scan_path = DATA_DIR / "misc" / "drive_scan_result.json"
    if not scan_path.exists():
        print(f"ERROR: drive_scan_result.json not found at {scan_path}")
        return

    with open(scan_path, "r", encoding="utf-8") as f:
        scan = json.load(f)

    scan_keys = list(scan.keys())
    print(f"Loaded {len(scan_keys)} drive scan keys.\n")

    total_scan_key_fixes = 0
    total_drive_id_injections = 0

    for thesis_id in all_thesis_ids():
        gdir = groups_dir(thesis_id)
        if not gdir.exists():
            continue

        label = thesis_id if thesis_id else "(root)"
        print(f"--- Thesis: {label} ---")

        for group_path in sorted(gdir.iterdir()):
            if not group_path.is_dir():
                continue

            meta_path = group_path / "group_meta.json"
            if not meta_path.exists():
                continue

            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            group_id = meta.get("group_id", group_path.name)
            title = meta.get("title", "")
            current_scan_key = meta.get("scan_key", "") or ""

            # ── Step 1: fix missing scan_key ────────────────────────────────
            best_key = match_scan_key(title, scan_keys)
            if not best_key:
                print(f"  [{group_id}] NO MATCH for title: '{title[:80]}'")
                continue

            if current_scan_key != best_key:
                meta["scan_key"] = best_key
                # atomic write
                tmp = meta_path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)
                tmp.replace(meta_path)
                print(f"  [{group_id}] scan_key SET: '{best_key[:80]}'")
                total_scan_key_fixes += 1
            else:
                print(f"  [{group_id}] scan_key OK:  '{best_key[:80]}'")

            # ── Step 2: inject drive_file_ids from scan dict ─────────────────
            scan_entry = scan.get(best_key, {})
            drive_links = scan_entry.get("drive_links", {}) or {}
            # Build filename -> drive_file_id from the shareable links
            # link format: https://drive.google.com/file/d/{id}/view
            drive_file_ids = {}
            for fname, link in drive_links.items():
                m = re.search(r'/file/d/([^/]+)/', link)
                if m:
                    drive_file_ids[fname] = m.group(1)

            sdir = sources_dir(group_path)
            if not sdir.exists() or not drive_file_ids:
                continue

            for src_path in sorted(sdir.glob("*.json")):
                with open(src_path, "r", encoding="utf-8") as f:
                    src = json.load(f)

                fname = src.get("file_name", "")
                if not fname or fname not in drive_file_ids:
                    continue

                new_id = drive_file_ids[fname]
                if src.get("drive_file_id") == new_id:
                    continue  # already correct

                src["drive_file_id"] = new_id
                src["drive_link"] = f"https://drive.google.com/file/d/{new_id}/view"

                tmp = src_path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(src, f, indent=2, ensure_ascii=False)
                tmp.replace(src_path)

                print(f"    -> injected drive_file_id into {src_path.name} ({fname})")
                total_drive_id_injections += 1

    print()
    print("=" * 50)
    print(f"scan_key fixes:           {total_scan_key_fixes}")
    print(f"drive_file_id injections: {total_drive_id_injections}")
    print("Done. Restart uvicorn to clear the in-memory cache.")


if __name__ == "__main__":
    main()
