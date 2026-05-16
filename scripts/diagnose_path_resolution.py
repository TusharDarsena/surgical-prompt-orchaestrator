"""
diagnose_path_resolution.py
----------------------------
Reproduces the exact call chain that _resolve_absolute_paths uses
when a subtopic run is triggered:

  1. Read drive_scan_result.json from ~/spo_data/misc/
  2. For each source_id in a failing subtopic, call _match_thesis_name()
  3. Check whether the stored folder_path actually exists on disk
  4. For each file in the scan entry, check whether the resolved abs_path exists

Run from the project root:
    python scripts/diagnose_path_resolution.py

Exit codes:
  0 = all paths resolved successfully
  1 = one or more paths are broken (the bug is confirmed)
"""

import json
import os
import sys

# ── 1. Load the scan from the correct spo_data location ──────────────────────

MISC_DIR = os.path.join(os.path.expanduser("~"), "spo_data", "misc")
SCAN_PATH = os.path.join(MISC_DIR, "drive_scan_result.json")

print(f"[CHECK] Loading scan from: {SCAN_PATH}")
if not os.path.isfile(SCAN_PATH):
    print(f"[FAIL]  File not found: {SCAN_PATH}")
    sys.exit(1)

with open(SCAN_PATH, encoding="utf-8") as f:
    scan = json.load(f)

print(f"[OK]    Loaded. {len(scan)} thesis entries found.\n")

# ── 2. Check every entry for stale folder_path ────────────────────────────────

stale = []
valid = []

for thesis_name, entry in scan.items():
    folder = (
        entry.get("folder_path")
        or entry.get("level4_path")
        or entry.get("level2_path")
        or ""
    )
    if not folder:
        stale.append((thesis_name, "NO FOLDER PATH STORED"))
    elif not os.path.isdir(folder):
        stale.append((thesis_name, folder))
    else:
        valid.append(thesis_name)

print(f"=== FOLDER PATH STATUS ===")
print(f"  Valid (folder exists on disk) : {len(valid)}")
print(f"  Stale (folder missing on disk): {len(stale)}")
print()

if stale:
    print("[STALE ENTRIES — these will always fail to upload:]")
    for name, path in stale:
        print(f"  ✕ {name[:70]}")
        print(f"    path: {path}")
    print()

# ── 3. Reproduce exact resolution for the known-failing subtopic ─────────────

FAILING_SOURCE_IDS = [
    {
        "source_id": "History and histography in the select novels of Salman Rushdie Amitav Ghosh and Mukul Kesavan",
        "chapter_id": "History and Historiography in Fiction (Chapter 1)",
        "file_name": "ch-1.pdf",
    },
    {
        "source_id": "THE USE OF HISTORY IN THE CONTEMPORARY INDIAN ENGLISH NOVEL",
        "chapter_id": "Exordium (Chapter 1)",
        "file_name": "05_chapter 1.pdf",
    },
    {
        "source_id": "THE USE OF HISTORY IN THE CONTEMPORARY INDIAN ENGLISH NOVEL",
        "chapter_id": "Historiographic Metafiction (Chapter 2)",
        "file_name": "06_chapter 2.pdf",
    },
    {
        "source_id": "History and histography in the select novels of Salman Rushdie Amitav Ghosh and Mukul Kesavan",
        "chapter_id": "Introduction",
        "file_name": "introduction.pdf",
    },
]

print("=== SIMULATING _resolve_absolute_paths FOR FAILING SUBTOPIC ===")
print("Subtopic: 1.1 The Positivist Illusion and Its Undoing\n")

any_broken = False

for src in FAILING_SOURCE_IDS:
    source_id = src["source_id"]
    file_name = src["file_name"]

    # -- Step A: exact match (what _match_thesis_name does first) --
    thesis_entry = scan.get(source_id)

    # -- Step B: case-insensitive fallback --
    if not thesis_entry:
        lower_id = source_id.lower()
        for k in scan:
            if k.lower() == lower_id:
                thesis_entry = scan[k]
                print(f"  [WARN] Case-insensitive match used for: {source_id[:60]}")
                break

    if not thesis_entry:
        print(f"  [FAIL] thesis_entry NOT FOUND in scan for source_id: {source_id[:70]}")
        any_broken = True
        continue

    # -- Step C: resolve folder --
    folder = (
        thesis_entry.get("folder_path")
        or thesis_entry.get("level4_path")
        or thesis_entry.get("level2_path")
        or ""
    )

    if not folder:
        print(f"  [FAIL] No folder path stored for: {source_id[:60]}")
        any_broken = True
        continue

    # -- Step D: check candidate path --
    candidate = os.path.join(folder, file_name)
    exists = os.path.isfile(candidate)

    status = "[OK]  " if exists else "[FAIL]"
    print(f"  {status} {file_name}")
    print(f"         folder : {folder}")
    print(f"         full   : {candidate}")
    print(f"         exists : {exists}")
    if not exists:
        any_broken = True
    print()

# ── 4. Summary and recommendation ────────────────────────────────────────────

print("=== DIAGNOSIS ===")
if not any_broken and not stale:
    print("[PASS] All paths resolved. The bug is NOT a stale path issue.")
    print("       Look elsewhere — check NLM auth or network connectivity.")
    sys.exit(0)
elif stale and any_broken:
    print("[CONFIRMED BUG] Stale folder_path in drive_scan_result.json.")
    print()
    print("  The scan was done when PDFs were at a different location.")
    print("  Those paths no longer exist on disk.")
    print()
    print("  FIX: Re-run the scan with the current PDF folder location.")
    print("  Go to Source Library > Card 02 (Drive Setup) > Scan Folder.")
    print()
    # Try to find where the files might be now
    print("  Looking for PDF files in common locations...")
    search_roots = [
        os.path.join(os.path.expanduser("~"), "Downloads"),
        os.path.join(os.path.expanduser("~"), "Documents"),
        "D:\\",
        "E:\\",
    ]
    for root in search_roots:
        if os.path.isdir(root):
            for dirpath, dirnames, filenames in os.walk(root):
                pdfs = [f for f in filenames if f.lower().endswith(".pdf")]
                if len(pdfs) >= 5:  # likely a thesis folder
                    print(f"    Found {len(pdfs)} PDFs in: {dirpath}")
                break  # only check one level deep per root
    sys.exit(1)
else:
    print("[PASS] Folder paths exist but files may still be missing inside them.")
    sys.exit(1)
