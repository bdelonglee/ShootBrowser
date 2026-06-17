# Notes & Bins — Feature Reference

This document covers two related features added to the Database page:
**take-level notes** (server-persisted) and **bin/playlist notes + export/import** (localStorage + server).

---

## 1. Take Notes

### What it does
Each take card in the Database view can carry a free-text note. The note:
- Is shown as a vivid amber flag (`⚑`) on the **folded** card title line when a note exists.
- Appears as an inline editable box at the **top of the expanded card** (before thumbnails).
- Persists on the server — survives page reloads and browser clears.

### Storage: `DATA/__DATABASE/notes.json`
```json
{
  "version": 1,
  "takes": {
    "<_override_key>": "Note text here",
    ...
  }
}
```
The key is `_override_key`, which is `recordId + "::" + takeId` (both UUIDs, stable across edits).
This file is excluded from DB source discovery via `_DB_JSON_EXCLUDED` in `server.py`.

### Server side (`server.py`)

| Helper | Purpose |
|---|---|
| `_notes_path()` | Returns `Path` to `notes.json` |
| `_load_notes()` | Reads and parses `notes.json`; returns `{"version":1,"takes":{}}` on error |
| `_save_notes(n)` | Writes `notes.json` with `indent=2` |
| `_apply_notes(rows, notes)` | Adds `row["_note"]` field to every row from `notes["takes"]` |

`_apply_notes` is called in `api_database()` after `_apply_overrides` and `_apply_omissions`:
```python
rows = _apply_notes(rows, _load_notes())
```

**Endpoint: `POST /api/notes/save`**
```json
// Request body
{ "key": "<_override_key>", "text": "Note text" }

// Response
{ "success": true }
```
Sending an empty `text` deletes the key from `notes.json`.

### Client side (`generate_html.py`)

**Flag on folded card** — in `renderDbCard()`:
```js
const hasNote = !!(row['_note'] || '').trim();
const noteFlagSlot = '<span class="db-note-flag-slot">'
    + (hasNote ? '<span class="db-note-flag" title="Has note">⚑</span>' : '')
    + '</span>';
```
The slot `<span class="db-note-flag-slot">` stays in the DOM at all times so the flag
can be updated in-place without collapsing the card.

**Note box in expanded card** — in `renderDbDetails()`:
```js
const noteText = (row['_note'] || '').trim();
const noteBox  = OFFLINE_MODE ? '' : _noteBoxHtml(overrideKey, noteText, false);
// noteBox is prepended before photoStrip in the returned HTML
```

**`_noteBoxHtml(overrideKey, note, editing)`**
Returns one of three states:
- `editing=true` → textarea + Save / Cancel buttons
- `editing=false, note non-empty` → display text + Edit / × buttons
- `editing=false, note empty` → `⚑ Add note…` button

All buttons carry `data-note-key="<overrideKey>"` so handlers can look up the row.

**Handlers:**
| Function | Action |
|---|---|
| `_doEditNote(btn)` | Swaps box to editing state via `box.outerHTML = _noteBoxHtml(key, note, true)` |
| `_doCancelNote(btn)` | Reverts to display state |
| `_doSaveNote(btn)` | `POST /api/notes/save`, updates `dbRows` in memory, refreshes box and flag slot |
| `_doClearNote(btn)` | `POST /api/notes/save` with `text:''`, removes note and flag |

**DOM update pattern** — to avoid re-rendering the whole card:
- `box.outerHTML = _noteBoxHtml(...)` replaces just the note box element.
- After save/clear, the flag slot is updated via `slot.innerHTML = ...` using `_entryByNoteKey(key)` which scans `[data-override-key]` elements.

---

## 2. Bin Notes

### What it does
Each bin/playlist (stored in `localStorage`) can carry a free-text note visible as a banner
at the top of the Database results when that bin is active.

### Storage
Bin notes live inside the bin object in `localStorage` under key `vfx_bins`:
```js
{
  "bin_<id>": {
    "id": "bin_<id>",
    "name": "Bin Name",
    "note": "Optional bin-level note",
    "items": [ { "type": "take"|"slate", "slate": "...", "take": "...", "camera": "..." } ]
  }
}
```
No server call is needed — bin notes are saved with `_saveBins()`.

### Banner element
```html
<div id="db-bin-note-banner" class="db-bin-note-banner" style="display:none"></div>
```
Placed after `#db-query-banner` in the HTML. Shown/hidden by `renderDatabase()`:
```js
const binNoteEl = document.getElementById('db-bin-note-banner');
if (activeBinId && bins[activeBinId]) {
    _renderBinNoteBanner(binNoteEl);
} else {
    binNoteEl.style.display = 'none';
}
```

### Functions
| Function | Action |
|---|---|
| `_renderBinNoteBanner(el)` | Renders bin name, note text, Edit note button, Export ↓ button |
| `_openBinNoteEdit()` | Replaces banner content with textarea + Save / Cancel |
| `_saveBinNote()` | Reads textarea, saves to `bin.note`, calls `_saveBins()`, re-renders banner |
| `_cancelBinNoteEdit()` | Re-renders banner in display mode |

---

## 3. Bin Export / Import

### Export

**Trigger:** Export button on each bin row in the Edit Bins modal, or Export ↓ button in
the active bin's note banner.

**Function: `_exportBin(binId)`**
1. Collects `bin.items` and `bin.note` from `bins[binId]`.
2. Iterates `dbRows` to find rows in the bin (`_rowInBin`) that have a `_note`.
3. Builds a portable JSON payload and triggers a browser download.

**Export file format:**
```json
{
  "version": 1,
  "format": "vfx_bin",
  "name": "Bin Name",
  "note": "Bin-level note",
  "exported_at": "YYYY-MM-DD",
  "items": [
    { "type": "take", "slate": "10/1", "take": "2", "camera": "A" },
    { "type": "slate", "slate": "49A/1" }
  ],
  "take_notes": [
    { "slate": "10/1", "take": "2", "camera": "A", "note": "Note text" }
  ]
}
```
Items use human-readable identifiers (`slate`, `take`, `camera`) — **not UUIDs** — so the
file is portable across database versions and machines.

**Filename:** `BinName_YYYY-MM-DD.json` (non-alphanumeric replaced with `_`).

### Import

**Trigger:** `⬆ Import Bin…` button at the bottom of the Edit Bins modal →
triggers a hidden `<input type="file" id="bin-import-input" accept=".json">`.

**Flow:**

1. **`_handleBinImport(inp)`** — reads the selected file with `FileReader`.
2. **`_parseBinImport(text)`**:
   - Validates `data.format === 'vfx_bin'`.
   - Builds a lookup `rowByKey` keyed by `slate|take|camera` from `dbRows`.
   - For each `take_note` in the file, finds the matching row. If the row already has a
     different note → conflict. If no note or same note → clean.
3. If conflicts exist → shows conflict modal (`_showConflictModal`).
   If no conflicts → calls `_applyBinImport` directly.
4. **`_applyBinImport(pending)`**:
   - Creates a new bin in `localStorage` with the imported name and items.
   - Applies conflict decisions (replace / merge / skip) to build a `toSave` list.
   - Saves each note via `POST /api/notes/save`.
   - Reloads `dbRows` from `/api/database` to pick up the new notes.
   - Calls `renderDatabase()`.

### Conflict modal

Injected into the DOM by the bin modal IIFE (same IIFE that creates `#bin-modal-overlay`).
Element ID: `#bin-conflict-overlay`.

Shows for each conflict:
- Take identifier (Slate / Take / Camera)
- Existing note vs. incoming note side-by-side
- Per-row radio: **Replace** | **Merge** | **Skip** (default: Merge)
- Batch buttons: **Replace All** | **Merge All** | **Skip All**
- **Cancel** and **Import** buttons

**Merge format:**
```
<existing note>
---
[YYYY-MM-DD] <incoming note>
```
The incoming note is always appended after the existing note, prefixed with the import date.

**State:** The pending import is stored in `window._pendingBinImport` while the modal is open.

---

## 4. CSS class reference

| Class | Element | Color |
|---|---|---|
| `.db-note-flag` | Amber flag `⚑` on folded card | `#f0a500` |
| `.db-note-flag-slot` | Wrapper span — always present in DOM | — |
| `.db-note-box` | Note display/edit container in expanded card | — |
| `.db-note-box.empty` | Note box when no note exists | — |
| `.db-note-textarea` | Editing textarea | amber focus border |
| `.db-bin-note-banner` | Full-width banner strip when bin is active | purple `#a371f7` |
| `.db-bin-note-export-btn` | Export ↓ button in banner | `#58a6ff` blue |
| `.bin-conflict-*` | All conflict modal elements | — |
| `.bin-modal-btn.export` | Export button in modal rows | `#58a6ff` blue |
| `.bin-modal-btn.import` | Import Bin… button at modal bottom | `#3fb950` green |

---

## 5. Important implementation notes

### Python f-string escaping (critical)
The entire HTML/JS lives in a Python triple-double-quoted f-string.
Two common mistakes that produce silent JS syntax errors:

| Wrong | Correct | Why |
|---|---|---|
| `'\n'` inside JS string literal | `'\\n'` | `'\n'` embeds a real newline → JS syntax error |
| `\'` for inner quote in JS `'...'` string | `&#39;` | `\'` in Python f-string → bare `'` → breaks JS string |

**To verify generated JS:** run  
```bash
python3 -c "
import generate_html, re
gen = generate_html.HTMLGenerator('.')
html = gen._build_html({})
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
open('/tmp/g.js','w').write('\n'.join(scripts))
" && node --input-type=module < /tmp/g.js
```
`ReferenceError: document is not defined` = no syntax errors (expected in Node).
Any `SyntaxError` = broken JS.

### Inline DOM update without card re-render
Note box edits use `box.outerHTML = _noteBoxHtml(...)` to swap just the box in-place.
The flag slot `<span class="db-note-flag-slot">` is always present in the card title line
so it can be updated independently via `slot.innerHTML = ...`.
This avoids collapsing an expanded card or discarding the photo strip scroll position.

### `_override_key` vs human-readable identifiers
- **Server storage** (`notes.json`) uses `_override_key` (UUID pair) — stable, fast lookup.
- **Export files** use `{slate, take, camera}` strings — portable, readable, survives DB regeneration.
- Import resolves human-readable → `_override_key` at import time by scanning `dbRows`.

### OFFLINE_MODE
When `OFFLINE_MODE` is true (offline HTML export), the note box is suppressed entirely
(`noteBox = ''`). No server calls are attempted. The export/import UI is still present
but will fail silently on the save step since there is no server.
