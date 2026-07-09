# Database Export — Feature Reference

Three export formats are available on the **Database page**, all operating on the currently
filtered rows (respecting all active search/filter/bin state).

## Toolbar layout

```
Line 1  [🎬 Scene] [🎭 VFX ID] [🎞 Slate] … group buttons … [Sort ▾] [↑] [N takes / N slates]
Line 2  [Slate ___] [VFX ID ___] [Date ___] [Camera ___] [Search ___] [Bin ▾] [SHOW OMITTED] [EDITED ONLY]  |  [⬇ CSV] [⬇ PDF] [⬇ HTML]
```

All three export buttons sit together at the right end of the filter row (line 2).
They are hidden in offline-mode pages (`.offline-mode` CSS class on `<body>`).

---

## 1. CSV Export

**No server call.** The browser builds and downloads the file directly.

### Client state (`generate_html.py`)
```js
const CSV_PRESETS_KEY = 'vfx_csv_presets';  // localStorage key
let csvPresets   = {};   // {id: {id, name, cols, sort}}
let csvModalCols = [];   // [{field, on}]  — checked = included, order = column order
let csvModalSort = { key: 'Slate', asc: true };
```

### Column pool
`CSV_ORDERED` defines the canonical display order for known fields. `_csvDefaultCols()`
builds the list from `Object.keys(dbRows[0])`, filtering out `_`-prefixed internal fields,
then sorts known fields by `CSV_ORDERED` and appends any extra fields at the end.

### JS functions

| Function | Purpose |
|---|---|
| `openCsvExportModal()` | Load presets, init cols if empty, show modal |
| `closeCsvExportModal()` | Hide modal |
| `_renderCsvModal()` | Re-render modal body (preset selector, col checklist+reorder, sort row) |
| `_csvSortKeyChange(val)` | Update `csvModalSort.key` |
| `_csvToggleSortDir()` | Toggle `csvModalSort.asc`, update button label |
| `_csvCurrentConfig()` | Snapshot `{cols, sort}` for preset saving |
| `_csvApplyConfig(cfg)` | Apply a loaded preset |
| `_csvLoadPreset()` | Read selected preset from `<select>`, apply, re-render |
| `_csvSavePreset()` | Save current config under a name |
| `_csvRenamePreset()` | `prompt()` rename |
| `_csvDeletePreset()` | Confirm + delete |
| `_doExportCsv()` | Build CSV blob, trigger download, close modal |

### Export logic (`_doExportCsv`)
1. `dbRows.filter(dbRowMatches)` — exactly what's on screen.
2. Sort by `csvModalSort.key` / `asc`.
3. Keep only checked columns in their current order.
4. Escape each cell: wrap in `"`, double internal `"`.
5. Join lines with `\r\n`, create `Blob('text/csv')`, trigger `<a>.click()`.
6. Filename: `database_export.csv` (fixed).

### Preset schema (localStorage `vfx_csv_presets`)
```json
{
  "preset_<timestamp>": {
    "id": "preset_<timestamp>",
    "name": "My preset",
    "cols": [{"field": "Slate", "on": true}, ...],
    "sort": {"key": "Slate", "asc": true}
  }
}
```

---

## 2. PDF Export

Two halves: a **client-side modal** that collects options, and a **server-side generator**
(`_generate_pdf` in `server.py`) that renders the PDF with ReportLab.

### Client state (`generate_html.py`)
```js
const PDF_PRESETS_KEY = 'vfx_pdf_presets';  // localStorage key

let pdfPresets     = {};     // {id: preset}
let pdfScope       = 'all';  // 'all' | 'filtered'
let pdfSortKey     = 'Slate';
let pdfSortAsc     = true;
let pdfLandscape   = true;   // default: landscape (more horizontal space for many columns)
let pdfInfoCols    = [];     // [{field, on}]  — info grid rows
let pdfTakeCols    = [];     // [{field, label, on}]  — takes table columns
let pdfShowVfxWork = true;
let pdfShowNotes   = true;
```

### Available fields

**Info grid** (`PDF_INFO_AVAIL`) — slate-level fields, shown in the 3-column header grid:
```
VFX ID, Set Location, Int/Ext, Day/Night, Unit, Shoot Day, Date, Wrangler, Set Refs
```

**Takes table** (`PDF_TAKE_AVAIL`) — first 9 are on by default, rest are opt-in:
```
Take, Camera, Roll, Lens, Focal, Shutter, FPS, f-stop, VFX        ← default ON
Body, Move, Res., Focus, Tilt, Height, WB, ISO, Filter, Take Notes, My Note (_note)
```

### JS functions

| Function | Purpose |
|---|---|
| `openPdfExportModal()` | Load presets, init cols if empty, show modal |
| `closePdfExportModal()` | Hide modal |
| `_renderPdfModal()` | Re-render full modal body |
| `_pdfSortKeyChange(v)` | Update `pdfSortKey` |
| `_pdfToggleSortDir()` | Toggle `pdfSortAsc` |
| `_pdfInfoUp/Down(i)` | Reorder info grid rows |
| `_pdfInfoCheckAll(on)` | Select/deselect all info fields |
| `_pdfTakeUp/Down(i)` | Reorder takes table columns |
| `_pdfTakeCheckAll(on)` | Select/deselect all take columns |
| `_pdfCurrentConfig()` | Snapshot all modal state for preset saving |
| `_pdfApplyConfig(cfg)` | Apply a loaded preset |
| `_pdfLoadPreset()` | Load selected preset, re-render |
| `_pdfSavePreset()` | Save current config under a name |
| `_pdfRenamePreset()` | `prompt()` rename |
| `_pdfDeletePreset()` | Confirm + delete |
| `_doPdfExport()` | Build request, POST to `/api/export-pdf`, download result |

### Export flow (`_doPdfExport`)
1. Read scope radio from DOM (`all` | `filtered`).
2. Filter and sort `dbRows` client-side.
3. Collect unique `slateIds` in sort order.
4. If scope = `filtered`: build `takeIds` list of `{slate, take, camera}` objects. If `all`: `null`.
5. Disable export buttons, close modal.
6. `POST /api/export-pdf`:
   ```json
   {
     "slates": ["10/1", "49A/1", ...],
     "take_ids": null | [{"slate": "10/1", "take": "2", "camera": "A"}, ...],
     "info_fields": ["VFX ID", "Set Location", ...],
     "take_cols": [{"field": "Take", "label": "Take"}, ...],
     "show_vfx_work": true,
     "show_notes": true,
     "landscape": true
   }
   ```
7. Receive blob, download as `<ProjectName>_YYYYMMDD.pdf`.

### Preset schema (localStorage `vfx_pdf_presets`)
```json
{
  "preset_<timestamp>": {
    "id": "preset_<timestamp>",
    "name": "My preset",
    "scope": "all",
    "sortKey": "Slate",
    "sortAsc": true,
    "landscape": true,
    "infoCols": [{"field": "VFX ID", "on": true}, ...],
    "takeCols": [{"field": "Take", "label": "Take", "on": true}, ...],
    "showVfxWork": true,
    "showNotes": true
  }
}
```

### Server endpoint: `POST /api/export-pdf` → `api_export_pdf()` (`server.py`)
1. Parse body.
2. `_load_db_json()` → `_denormalize_json_to_rows()` → `_apply_overrides()` → `_apply_notes()`.
3. Build `take_set` from `take_ids` when scope = filtered.
4. Group rows per slate into `slate_rows`, applying filter.
5. Call `_generate_pdf(buf, ...)`, stream as `application/pdf`.

### `_generate_pdf()` signature
```python
def _generate_pdf(
    buf,                    # writable BytesIO
    project_name: str,
    ordered_slates: list,   # slate IDs in display order
    slate_rows: dict,       # {slate_id: [row, ...]}
    records_by_slate: dict, # {slateId: record}  — for reference photos
    info_fields=None,       # [str]  defaults to PDF_INFO_FIELD_DEFAULTS
    take_cols=None,         # [{field, label}]  defaults to PDF_TAKE_COL_DEFAULTS
    show_vfx_work=True,
    show_notes=True,
    landscape=True,         # A4 landscape ≈ 247 mm usable; portrait ≈ 174 mm
) -> None
```

### Server-side constants (`server.py`, before `_generate_pdf`)

| Constant | Purpose |
|---|---|
| `PDF_INFO_FIELD_DEFAULTS` | Default 9 info-grid fields |
| `PDF_TAKE_COL_DEFAULTS` | Default 9 take columns |
| `PDF_TAKE_COL_WEIGHTS` | Proportional width weight per field — `CW * weight / total_weight` |
| `PDF_TAKE_COL_STYLES` | Per-field cell style: `'center'`, `'mono'`, `'vfx'`, or `'normal'` |

A field not in `PDF_TAKE_COL_WEIGHTS` gets fallback weight `1.5`.

### PDF page layout

**Cover page:** project title · stats table (export date, slate/take counts, cameras, lenses, date range) · slate index grid · `PageBreak`

**Per-slate page:**
```
┌──────────────────────────────────────────────────────────┐
│  SLATE 10/1          Scene Description                   │  ← navy header bar
├──────────────────────────────────────────────────────────┤
│  [photo 1]  [photo 2]  [photo 3]  [photo 4]             │  ← up to 4 photos, 60 mm tall
├──────────────────────────────────────────────────────────┤
│  VFX ID │ value  │  Set Location │ value  │  ...        │  ← info grid (3-col, dynamic)
├──────────────────────────────────────────────────────────┤
│  VFX Work  │ <text>                                      │  ← optional text section
│  Notes     │ <text>                                      │  ← optional text section
├──────────────────────────────────────────────────────────┤
│  3 takes  ·  Cam A  ·  Cooke 25mm  ·  25 fps            │  ← summary line (blue bg)
├──────────────────────────────────────────────────────────┤
│  SLATE 10/1  (full-width, navy)                          │  ← repeatRows=2: repeats on overflow
│  Take │ Camera │ Roll │ Lens │ ...                       │  ← column header row (also repeats)
│  1    │ A      │ ...  │ ...  │ ...                       │  ← alternating-bg data rows
│  2    │ A      │ ...  │  VFX │ ...                       │  ← VFX takes: green bg
└──────────────────────────────────────────────────────────┘
```

`repeatRows=2` means both the slate label and the column header repeat at the top of every
continuation page — it is always clear which slate the takes belong to.

**Footer (every page):** project name (left) · export date (centre) · Page N (right)

### Adding a new takes-table field
1. `generate_html.py` → add to `PDF_TAKE_AVAIL`: `{field: 'MyField', label: 'My Label'}`
2. `server.py` → add weight to `PDF_TAKE_COL_WEIGHTS`: `'MyField': 1.5`
3. Optionally add to `PDF_TAKE_COL_STYLES` for centered/mono rendering.
4. Default-on columns = `PDF_TAKE_AVAIL.slice(0, 9)` — adjust the slice if needed.

---

## 3. Offline HTML Export

**No preset system.** One click, no modal. The exported page is fully self-contained —
no server, no network, no localStorage needed.

### What it exports
Exactly `dbRows.filter(dbRowMatches)` — the rows currently visible on screen.
The database filtering, sorting, grouping, and card expand/collapse all work in the
exported file. There are no other tabs (tab bar is hidden).

### Client function: `_doExportDbHtml()` (`generate_html.py`)
1. Collect `rows = dbRows.filter(dbRowMatches)`.
2. Disable the `⬇ HTML` button, show `⏳`.
3. `POST /api/export-db-html` with `{rows}`.
4. Receive blob, download as `database_export.html`.
5. Re-enable button.

### Server endpoint: `POST /api/export-db-html` → `api_export_db_html()` (`server.py`)
```python
rows = request.json.get("rows") or []
g    = make_generator()
html = g._build_html(
    g.build_data(),
    offline_data={"db_rows": rows, "delivered": [], "photos": {}},
    db_only=True,
)
# Return as text/html download
```

### `_build_html(db_only=True)` behaviour (`generate_html.py`)
Two flags are set when `db_only=True`:

| JS constant | Value | Effect |
|---|---|---|
| `OFFLINE_MODE` | `true` | Disables all server calls (notes, overrides, etc.) |
| `DB_ONLY_MODE` | `true` | Adds `.db-only-mode` to `<body>`, forces `setView('database')` on load |

CSS when `.db-only-mode` is on the body:
```css
.db-only-mode .tab-bar             { display: none !important; }
.db-only-mode #offline-html-btn    { display: none !important; }
.db-only-mode #offline-html-status { display: none !important; }
```

JS at init (after `_restoreUiState()`):
```js
if (DB_ONLY_MODE) {
    document.body.classList.add('db-only-mode');
    setView('database');
}
```

`_restoreUiState()` skips the `setView(s.view)` call when `DB_ONLY_MODE` is true,
so the saved tab preference from the user's localStorage never overrides the forced view.

### What works / what doesn't in the exported file

| Feature | Works? | Notes |
|---|---|---|
| Filter fields (Slate, VFX ID, Date…) | ✅ | Pure client-side |
| Sort / group mode buttons | ✅ | Pure client-side |
| Card expand / collapse | ✅ | Pure client-side |
| Reference photos | ✅ | Embedded in `offlinePhotos` via regular offline mechanism |
| Take notes display | ✅ | Embedded in rows as `_note` field |
| Save / edit notes | ✗ | Requires server (`OFFLINE_MODE = true`) |
| Bins | ✗ | localStorage bins from the live app are not carried over |
| CSV / PDF export from within the exported page | ✗ | Buttons hidden (`.offline-mode`) |
