import json
import os
import re
from pathlib import Path

def slugify(text: str) -> str:
    # Basic slugification: lower case, replace non-alphanumeric with underscore
    text = re.sub(r'[^a-zA-Z0-9]', '_', text)
    # Collapse multiple underscores
    text = re.sub(r'_+', '_', text)
    return text.lower().strip('_')

def advanced_match(source_id: str, scan: dict) -> str | None:
    # 1. Exact match
    if source_id in scan:
        return source_id
    
    # 2. Case-insensitive
    lower_id = source_id.lower()
    for k in scan:
        if k.lower() == lower_id:
            return k
            
    # 3. Slugified match
    slug_id = slugify(source_id)
    for k in scan:
        if slugify(k) == slug_id:
            return k
            
    # 4. Partial substring match (fuzzy) - sometimes source_ids are truncated
    for k in scan:
        if slugify(k).startswith(slug_id):
            return k
    for k in scan:
        if slug_id.startswith(slugify(k)):
            return k

    # 5. Difflib fuzzy matching for typos (like "woman" vs "women") or severe truncation
    import difflib
    scan_slugs = {slugify(k): k for k in scan}
    matches = difflib.get_close_matches(slug_id, scan_slugs.keys(), n=1, cutoff=0.8)
    if matches:
        return scan_slugs[matches[0]]

    # If cutoff 0.8 fails, maybe check for substring matches with difflib
    # specifically for long truncated strings
    for scan_slug, k in scan_slugs.items():
        if len(scan_slug) > 20 and len(slug_id) > 20:
            # If they share a very long common prefix
            common_prefix = os.path.commonprefix([scan_slug, slug_id])
            if len(common_prefix) > 30: # arbitrary threshold for a "very long" prefix
                return k

    return None

def main():
    chapters_dir = Path(r"c:\Users\asus\Desktop\surgical prompt orchaestrator\a_synopsis\chapterizations\bh")
    scan_file = Path(r"c:\Users\asus\spo_data\misc\drive_scan_result.json")
    
    if not scan_file.exists():
        print(f"Scan file not found: {scan_file}")
        return
        
    with open(scan_file, "r", encoding="utf-8") as f:
        scan = json.load(f)
        
    source_ids = set()
    for chapter_file in chapters_dir.glob("*.json"):
        with open(chapter_file, "r", encoding="utf-8") as f:
            chapter = json.load(f)
            for sub in chapter.get("subtopics", []):
                for src in sub.get("source_ids", []):
                    sid = src.get("source_id", "").strip()
                    if sid:
                        source_ids.add(sid)
            for reserved in chapter.get("sources_reserved_for_later_chapters", []):
                sid = reserved.get("source_id", "").strip()
                if sid:
                    source_ids.add(sid)
                    
    print(f"Found {len(source_ids)} unique source IDs in chapters.")
    
    success_count = 0
    failures = []
    
    for sid in sorted(source_ids):
        match = advanced_match(sid, scan)
        if match:
            success_count += 1
            print(f"[OK] {sid} => {match}")
        else:
            failures.append(sid)
            print(f"[FAIL] {sid}")
            
    print(f"\nResults: {success_count} / {len(source_ids)} matched ({(success_count/len(source_ids))*100 if source_ids else 0:.2f}%)")
    
    if failures:
        print("\nFailed to match:")
        for f in failures:
            print(f" - {f}")

if __name__ == '__main__':
    main()
