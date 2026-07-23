# Notes & Bins — Feature Reference

This document covers the note layers on take cards and the bin/playlist system on the Database page.

---

## 1. Take Notes — Two Independent Layers

Each take card carries **two separate note fields**, both server-persisted and independent of the database JSON:

| Layer | Field | Color | Purpose | Storage |
|---|---|---|---|---|
| Internal note | `_note` | Amber `#f0a500` | Private production notes | `notes.json` |
| Shared note | `_shared_note` | Blue `#58a6ff` | Vendor-facing delivery notes | `shared_notes.json` |

Both appear in the expanded card inside a `.db-note-section` wrapper, internal note first.  
Both show a flag `⚑` on the **folded** card title line when a note exists.  
In **offline HTML exports**: internal note is suppressed; shared note is shown read-only.

### Layout in expanded card

```
┌── .db-note-section ─────────────────────────────────────────────┐
│ [amber ⚑] [internal note text / textarea]  [Edit] [×]          │
│ (5px gap)                                                        │
│ [blue ⚑]  [shared note text / textarea]    [Edit] [×]          │
└─────────────────────────────────────────────────────────────────┘
  16px margin-bottom
┌── .db-photo-strip ──────────────────────────────────────────────┐
│ [photo thumbnails…]                                             │
└─────────────────────────────────────────────────────────────────┘
```

`.db-note-section` is a flex column with `gap: 5px` and `margin-bottom: 0`. The 16px gap to the photo strip is on `.db-photo-strip { margin-bottom: 16px }` (photos are rendered *above* notes in the DOM).

---

## 2. Internal Note (`_note`)

### Storage: `DATA/__DATABASE/notes.json`
```json
{
  "version": 1,
  "takes": {
    "<_override_key>": "Note text here"
  }
}
```
Key is `_override_key` = `recordId + "::" + takeId`. Excluded from DB discovery via `_DB_JSON_EXCLUDED`.

### Server side

| Helper | Purpose |
|---|---|
| `_notes_path()` | Path to `notes.json` |
| `_load_notes()` | Reads file; returns `{"version":1,"takes":{}}` on error |
| `_save_notes(n)` | Writes with `indent=2` |
| `_apply_notes(rows, notes)` | Adds `row["_note"]` to every row |

Called in all three row-loading paths: `api_database()`, `api_extract_slates_export()`, `api_export_pdf()`.

**Endpoint: `POST /api/notes/save`**
```json
{ "key": "<_override_key>", "text": "Note text" }
```
Empty `text` deletes the key.

### Client side

**`_noteBoxHtml(overrideKey, note, editing)`** — three states:
- `editing=true` → textarea + Save / Cancel
- `note` non-empty → display text + Edit / ×
- empty → `⚑ Add internal note…` button (always suppressed in `OFFLINE_MODE`)

**Handlers:** `_doEditNote`, `_doCancelNote`, `_doSaveNote`, `_doClearNote`  
After save/clear, updates `dbRows` in memory and refreshes the amber flag slot in-place.

---

## 3. Shared Note (`_shared_note`)

### Storage: `DATA/__DATABASE/shared_notes.json`
Same structure as `notes.json`. Also excluded from `_DB_JSON_EXCLUDED`.

### Server side

| Helper | Purpose |
|---|---|
| `_shared_notes_path()` | Path to `shared_notes.json` |
| `_load_shared_notes()` | Reads file; returns `{"version":1,"takes":{}}` on error |
| `_save_shared_notes(n)` | Writes with `indent=2` |
| `_apply_shared_notes(rows, notes)` | Adds `row["_shared_note"]` to every row |

Called immediately after `_apply_notes` in all three row-loading paths.

**Endpoint: `POST /api/shared-notes/save`**
```json
{ "key": "<_override_key>", "text": "Note text" }
```

### Client side

**`_sharedNoteBoxHtml(overrideKey, note, editing)`** — three states:
- `editing=true` → textarea + Save / Cancel
- `note` non-empty, `OFFLINE_MODE` false → display text + Edit / ×
- `note` non-empty, `OFFLINE_MODE` true → display text only (read-only, no buttons)
- empty, `OFFLINE_MODE` false → `⚑ Add shared note…` button
- empty, `OFFLINE_MODE` true → returns `''` (nothing rendered)

**Handlers:** `_doEditSharedNote`, `_doCancelSharedNote`, `_doSaveSharedNote`, `_doClearSharedNote`  
Uses `data-shared-note-key` attribute (not `data-note-key`) to avoid collision with internal note handlers.

### Notes section rendering (`renderDbDetails`)
```js
const notesSection = (OFFLINE_MODE && !sharedNoteBox)
    ? ''
    : `<div class="db-note-section">${OFFLINE_MODE ? '' : noteBox}${sharedNoteBox}</div>`;
```
In offline mode: renders the section only if `sharedNoteBox` is non-empty, and omits `noteBox`.

---

## 4. Export behaviour per note field

| Export | Internal Note (`_note`) | Shared Note (`_shared_note`) |
|---|---|---|
| Offline HTML | Suppressed | Shown read-only (if non-empty) |
| CSV column picker | Selectable — label **"Internal Note"**, off by default | Selectable — label **"Shared Note"**, off by default |
| PDF column picker | Selectable — label **"Internal Note"** | Selectable — label **"Shared Note"** |
| Default CSV cols | Excluded (underscore-prefixed filter) | Excluded (added manually) |
| Default PDF cols | Not in `PDF_TAKE_COL_DEFAULTS` | Not in `PDF_TAKE_COL_DEFAULTS` |

`PDF_TAKE_COL_WEIGHTS` assigns `3.0` to both `_note` and `_shared_note` (same width as `Take Notes`).

The CSV column picker also displays `Take Notes` (from the database JSON) with the friendly label **"Take note"**, implemented via the `CSV_LABELS` map inside `_csvDefaultCols()`.

CSV presets save the full `csvModalCols` array including any `_shared_note` / `_note` entries, so preset recall restores the selection correctly.

---

## 5. Bin Notes

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

### Banner layout (two-line)

**Display mode:**
```
┌──────────────────────────────────────────────────────┐
│ Bin Name   3 Takes · 2 Slates (7 takes)    [⚙]  [×] │
│ note text here…                  [Edit note] [Export ↓] │
└──────────────────────────────────────────────────────┘
```
- Top row (`.db-bin-note-banner-top`): name · count · spacer · ⚙ manage · × deactivate
- Body row (`.db-bin-note-banner-body`): note text · Edit note · Export ↓

**Edit mode** (after clicking "Edit note"):
- `Cmd/Ctrl+Enter` saves, `Escape` cancels.
- The top row shows name + count but hides ⚙ and × while editing.

### Functions
| Function | Action |
|---|---|
| `_renderBinNoteBanner(el)` | Renders two-line display mode (calls `_binCountLabel`) |
| `_openBinNoteEdit()` | Replaces banner body with textarea + Save/Cancel; wires keyboard shortcuts |
| `_saveBinNote()` | Reads textarea, saves to `bin.note`, calls `_saveBins()`, re-renders banner |
| `_cancelBinNoteEdit()` | Re-renders banner in display mode |

### ⚙ and × buttons
- **⚙** calls `openBinModal()` — jumps to the bin manager modal without touching the active bin.
- **×** calls `setActiveBin('')` — clears `activeBinId`, hides the banner, and resets the bin combobox to "No Bin".

### `setActiveBin(val)` — combobox sync
```js
activeBinId = val || null;
const sel = document.getElementById('bin-select');
if (sel) sel.value = activeBinId || '';
renderDatabase();
_saveUiState();
```

---

## 6. Bin Modal UI

Opened via `openBinModal()`, injected into the DOM by an IIFE at page init.

```
┌─────────────────────────────────────────────┐
│ Bins                           [+ New Bin]  │
├─────────────────────────────────────────────┤
│ ● Bin Name A              ✎  [Export ↓] [Delete] │
│   3 Takes · 2 Slates (7 takes)             │
│   first line of note…                      │
├─────────────────────────────────────────────┤
│ ● Bin Name B (active, purple highlight) ✎  │
│   5 Takes                                  │
├─────────────────────────────────────────────┤
│ [⬆ Import Bin…]                            │
├─────────────────────────────────────────────┤
│ [Close]                                    │
└─────────────────────────────────────────────┘
```

### Functions

| Function | Action |
|---|---|
| `openBinModal()` | Calls `_renderBinModal()`, shows overlay |
| `closeBinModal()` | Hides overlay |
| `_renderBinModal()` | Rebuilds `#bin-modal-list` HTML |
| `_binCountLabel(bin)` | Returns `"3 Takes · 2 Slates (7 takes)"` string |
| `_modalToggleActive(binId)` | Activates/deactivates bin without closing modal, re-renders modal |
| `_startRenameBin(binId)` | Replaces `.bin-modal-name-row` with inline input + ✓/✕ |
| `_doRenameBin(binId)` | Saves rename, re-renders modal + select + database |
| `_cancelRenameBin()` | Re-renders modal (restores name display) |
| `_newBinFromModal()` | Inserts a temp input row at top of list for inline bin creation |
| `_doCreateBinModal()` | Creates empty bin from the inline input, re-renders |
| `deleteBin(binId)` | Confirm then delete, deactivates if was active |

---

## 7. Removing Items from Bins

### The `−` button
Shown on each take card when the take belongs to at least one bin (`_inAnyBin`).
`_rowInBin(row, bin)` matches both `type:'take'` items (exact match) and `type:'slate'`
items (any take from that slate).

### Remove flow

**When inside an active bin (`activeBinId` is set):**
- Individual take item → confirm dialog → `_removeItemFromBin`
- Slate item → dropdown: `− Just this take` / `− All N takes from slate X`

**When outside any active bin:**
- `_openRemoveMenu` shows a list of bins containing the take.
- For slate items, two sub-entries per bin (`"BinName — just this take"` and `"BinName — all N takes"`).

### Key functions

| Function | Action |
|---|---|
| `_confirmRemoveFromBin(e, btn)` | Entry point from the `−` button |
| `_openSlateRemoveChoice(btn, binId, slate, take, cam, slateCount)` | Shows `#bin-menu` with just/all choice |
| `_openRemoveMenu(e, btn, item)` | Shows `#bin-menu` listing bins |
| `_removeItemFromBin(binId, item)` | Exact-match filter on `{type, slate, take, camera}` |
| `_doRemoveJustTake(binId, slate, take, camera)` | Removes slate item, re-adds all other takes individually |
| `_doRemoveWholeSlate(binId, slate)` | Removes all items (slate or take) for that slate |
| `_doRemoveFromBin(binId, slate, take, camera)` | Removes an exact take item from outside-bin menu |

---

## 8. Bin Export / Import

### Export

**Function: `_exportBin(binId)`**
1. Collects `bin.items` and `bin.note`.
2. Iterates `dbRows` to find rows in the bin that have a `_note`.
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
Items use human-readable identifiers — **not UUIDs** — portable across DB versions.

**Note:** `take_notes` in the bin export carries `_note` (internal note) only, not `_shared_note`.

### Import flow
1. **`_handleBinImport(inp)`** — reads file with `FileReader`
2. **`_parseBinImport(text)`** — validates format, checks for conflicts against existing `_note` values
3. Conflicts → `_showConflictModal`; no conflicts → `_applyBinImport` directly
4. **`_applyBinImport(pending)`** — creates bin, saves notes via `POST /api/notes/save`, reloads `dbRows`

### Conflict modal (`#bin-conflict-overlay`)
Per-row radio: **Replace** | **Merge** | **Skip** (default: Merge).  
Merge format: `<existing>\n---\n[YYYY-MM-DD] <incoming>`.  
Pending state stored in `window._pendingBinImport`.

---

## 9. CSS class reference

### Internal note (amber)
| Class | Element |
|---|---|
| `.db-note-flag` | Amber `⚑` flag on folded card (`#f0a500`) |
| `.db-note-flag-slot` | Wrapper span — always in DOM for in-place update |
| `.db-note-box` | Note container — amber left border |
| `.db-note-box.empty` | Dashed amber border, no background |
| `.db-note-box-icon` | `⚑` icon inside box |
| `.db-note-textarea` | Editing textarea — amber focus border |
| `.db-note-add-btn` | "Add internal note…" button (muted amber, no border) |
| `.db-note-edit-btn` | Edit button (amber hover) |
| `.db-note-save-btn` | Save button (amber fill) |
| `.db-note-cancel-btn`, `.db-note-clear-btn` | Gray utility buttons |

### Shared note (blue)
| Class | Element |
|---|---|
| `.db-shared-note-flag` | Blue `⚑` flag on folded card (`#58a6ff`) |
| `.db-shared-note-flag-slot` | Wrapper span — always in DOM |
| `.db-shared-note-box` | Note container — blue left border |
| `.db-shared-note-box.empty` | Dashed blue border, no background |
| `.db-shared-note-box-icon` | `⚑` icon inside box |
| `.db-shared-note-textarea` | Editing textarea — blue focus border |
| `.db-shared-note-add-btn` | "Add shared note…" button (muted blue) |
| `.db-shared-note-edit-btn` | Edit button (blue hover) |
| `.db-shared-note-save-btn` | Save button (blue fill) |
| `.db-shared-note-cancel-btn`, `.db-shared-note-clear-btn` | Gray utility buttons |

### Note section wrapper
| Class | Element |
|---|---|
| `.db-note-section` | Flex column wrapping both note boxes; `gap: 5px`, `margin-bottom: 0` |

### Bin notes
| Class | Element |
|---|---|
| `.db-bin-note-banner` | Full-width banner strip — purple left border `#a371f7` |
| `.db-bin-note-banner-top` | Top row: name · count · spacer · ⚙ · × |
| `.db-bin-note-banner-name` | Bin name in purple |
| `.db-bin-note-banner-count` | Count label (muted) |
| `.db-bin-note-banner-body` | Second row: note text + action buttons |
| `.db-bin-note-manage-btn` | ⚙ button (purple hover) |
| `.db-bin-note-deactivate-btn` | × button (red hover `#f47067`) |
| `.db-bin-note-export-btn` | Export ↓ (blue `#58a6ff`) |
| `.bin-modal-*` | Bin modal rows, rename, count, snippet, buttons |
| `.bin-remove-btn` | `−` button on take card (red hover) |

---

## 10. Important implementation notes

### Python f-string escaping (critical)
| Wrong | Correct | Why |
|---|---|---|
| `'\n'` inside JS string | `'\\n'` | Embeds a real newline → JS syntax error |
| `\'` for inner quote | `&#39;` | `\'` in f-string → bare `'` → breaks JS string |

**Verify generated JS:**
```bash
python3 -c "
import generate_html, re
gen = generate_html.HTMLGenerator('.')
html = gen._build_html({})
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
open('/tmp/g.js','w').write('\n'.join(scripts))
" && node --input-type=module < /tmp/g.js
```
`ReferenceError: document is not defined` = clean. Any `SyntaxError` = broken JS.

### Inline DOM update without card re-render
Both note boxes use `box.outerHTML = _*NoteBoxHtml(...)` to swap in-place.  
Flag slots (`.db-note-flag-slot`, `.db-shared-note-flag-slot`) are always present in the DOM so they can be updated independently without collapsing the card.

### `data-note-key` vs `data-shared-note-key`
Internal note handlers read `btn.dataset.noteKey`; shared note handlers read `btn.dataset.sharedNoteKey`. The two attributes are distinct so handlers on nested elements never collide.

### `_override_key` vs human-readable identifiers
- **Server storage** (`notes.json`, `shared_notes.json`) — keyed by `_override_key` (UUID pair), stable across edits.
- **Bin export files** — keyed by `{slate, take, camera}` strings, portable across DB regenerations.
- Import resolves human-readable → `_override_key` at import time by scanning `dbRows`.

### Photo strip position
`.db-photo-strip` is rendered *above* `.db-note-section` in the DOM (either inline in `renderDbDetails` or injected via `_injectPhotoStrip` with `afterbegin`). The 16px gap between strip and notes is on `.db-photo-strip { margin-bottom: 16px }`, not on the note section.
