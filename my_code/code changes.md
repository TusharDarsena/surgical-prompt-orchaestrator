Here are the three exact changes you need to apply:

---

**File 1: `spo_backend/routers/drive.py`**

Find this:
```python
class ScanRequest(BaseModel):
    root_path: str
```
Replace with:
```python
class ScanRequest(BaseModel):
    root_path: str
    thesis_folder_name: Optional[str] = None  # when set, scopes scan to root/thesis_folder_name only
```

---

Find this block (starts after the `is_dir` check):
```python
    existing_scan = _read_scan()
    added = []

    # 1. Find EVERY PDF safely (case-insensitive to catch .PDF and .pdf)
    pdf_files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]

    # 2. Group PDFs by their parent directory
    thesis_folders: dict[Path, list[str]] = {}
    for pdf in pdf_files:
        parent_dir = pdf.parent
        thesis_folders.setdefault(parent_dir, []).append(pdf.name)

    # 3. CLEANUP STALE FOLDERS: Remove entries that were deleted from the filesystem
    current_thesis_names = {folder.name for folder in thesis_folders.keys()}
    keys_to_delete = []
    
    for t_name, t_data in existing_scan.items():
        # Get stored path (supporting both new and old key names)
        t_path_str = t_data.get("folder_path") or t_data.get("level2_path", "")
        if not t_path_str:
            continue
            
        t_path = Path(t_path_str)
        # If the stored folder was inside the directory we are currently scanning,
        # but we didn't find it this time, it means it was deleted from the disk!
        if t_path.is_relative_to(root) and t_name not in current_thesis_names:
            keys_to_delete.append(t_name)
```
Replace with:
```python
    # If thesis_folder_name is provided, scope the scan to root/thesis_folder_name only.
    # This prevents the cleanup step from touching entries belonging to other theses.
    if req.thesis_folder_name:
        scan_root = root / req.thesis_folder_name
        if not scan_root.is_dir():
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Folder '{req.thesis_folder_name}' not found inside '{root}'. "
                    "Make sure the thesis title matches the Level 2 folder name exactly."
                )
            )
    else:
        scan_root = root  # legacy full-scan behaviour

    existing_scan = _read_scan()
    added = []

    # 1. Find EVERY PDF safely (case-insensitive to catch .PDF and .pdf)
    pdf_files = [p for p in scan_root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]

    # 2. Group PDFs by their parent directory
    thesis_folders: dict[Path, list[str]] = {}
    for pdf in pdf_files:
        parent_dir = pdf.parent
        thesis_folders.setdefault(parent_dir, []).append(pdf.name)

    # 3. CLEANUP STALE FOLDERS: Remove entries that were deleted from the filesystem
    current_thesis_names = {folder.name for folder in thesis_folders.keys()}
    keys_to_delete = []

    for t_name, t_data in existing_scan.items():
        # Get stored path (supporting both new and old key names)
        t_path_str = t_data.get("folder_path") or t_data.get("level2_path", "")
        if not t_path_str:
            continue

        t_path = Path(t_path_str)
        # Only consider entries whose folder lives inside scan_root (not the full root).
        # Scoped scans must never delete entries belonging to other theses.
        if t_path.is_relative_to(scan_root) and t_name not in current_thesis_names:
            keys_to_delete.append(t_name)
```

---

**File 2: `spo_frontend/static/js/source_library_api.js`**

Find:
```js
export const scanLocalFolder = (rootPath) =>
  _post("/drive/scan-local", { root_path: rootPath });
```
Replace with:
```js
export const scanLocalFolder = (rootPath, thesisFolderName = null) => {
  const body = { root_path: rootPath };
  if (thesisFolderName) body.thesis_folder_name = thesisFolderName;
  return _post("/drive/scan-local", body);
};
```

---

**File 3: `spo_frontend/static/js/source_library.js`**

Find:
```js
async function handleScan() {
  const path = $("scanPath").value.trim();
  if (!path) { toast("Enter a folder path first", "error"); return; }
  const btn = $("btnScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const result = await API.scanLocalFolder(path);
    toast(`Scan complete — ${result.total_thesis_folders ?? 0} folders found`, "success");
    await loadThesisFolders();
  } catch (err) {
    toast(`Scan failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false; btn.textContent = "🔍 Scan Folder";
  }
}
```
Replace with:
```js
async function handleScan() {
  const path = $("scanPath").value.trim();
  if (!path) { toast("Enter a folder path first", "error"); return; }

  // Resolve the active thesis title — used to scope the scan to one Level 2 folder.
  // Without this, the cleanup step would consider ALL entries under the root as candidates
  // for deletion, which would wipe Drive links for theses you're not working on.
  const activeId = _activeThesisId();
  if (!activeId) { toast("Select an active thesis first", "error"); return; }
  const theses = _loadThesesIndex();
  const activeThesis = theses.find(t => t.id === activeId);
  if (!activeThesis?.title) { toast("Active thesis has no title — reload the page", "error"); return; }
  const thesisFolderName = activeThesis.title;

  const btn = $("btnScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const result = await API.scanLocalFolder(path, thesisFolderName);
    toast(`Scan complete — ${result.total_thesis_folders ?? 0} folders found`, "success");
    await loadThesisFolders();
  } catch (err) {
    toast(`Scan failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false; btn.textContent = "🔍 Scan Folder";
  }
}
```