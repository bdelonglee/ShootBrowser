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

## 3. Offline HTML Export — two separate mechanisms

There are two completely different HTML export paths. They share the same `_build_html()`
engine but differ in scope, output format, photo handling, and intended use.

---

### Quick comparison

| | Browse page `💾 Offline HTML` | Database page `⬇ HTML` |
|---|---|---|
| **Trigger** | Button in browse toolbar | Popup on filter row |
| **Scope** | Entire database + browse data | Currently filtered rows only |
| **Output format** | Multi-file (HTML + `photos/` folder) | Single self-contained `.html` |
| **Photo format** | Separate `.jpg` files (relative paths) | Base64 data URIs (inline) |
| **Photo choice** | Always exported (all slates) | Optional: without / with |
| **Where it lands** | `SHOOT_BROWSER/OfflineSite/` on server, opened in new tab | Downloaded via browser to user's machine |
| **Views in exported file** | All tabs (browse, database, delivered…) | Database view only |
| **JS flags** | `OFFLINE_MODE=true` | `OFFLINE_MODE=true` + `DB_ONLY_MODE=true` |

---

### 3a. Browse page — `💾 Offline HTML`

**Location:** Browse page toolbar (sort controls row, first line).

**Purpose:** Full snapshot of the entire project — all slates, all takes, all delivered items,
all reference photos — as a multi-file package that can be shared or archived.

#### Client function: `generateOfflineHtml()` (`generate_html.py`)
1. Open a blank browser tab immediately (must be in click-handler context, before any `await`).
2. `POST /api/generate-offline-html`.
3. On success, navigate the new tab to `/offline-site/vfx_shoot_browser_offline.html`.

#### Server endpoint: `POST /api/generate-offline-html` → `api_generate_offline_html()` (`server.py`)
Calls `generator.generate_offline_html()` → returns `{"success": true, "path": "..."}`.

#### `generate_offline_html()` (`generate_html.py`)
Writes files to `SHOOT_BROWSER/OfflineSite/`:
```
OfflineSite/
  vfx_shoot_browser_offline.html   ← main app
  photos/
    10_1_0.jpg                     ← one file per photo, named {slate_safe}_{index}.jpg
    10_1_1.jpg
    49A_1_0.jpg
    ...
```

Photos are decoded from the base64 data URIs stored in the JSON database and written as
real JPEG files. The HTML references them as `./photos/<filename>` (relative paths).
This keeps the HTML file small even with many photos.

`_extract_offline_photos(photos_dir)` returns `{slate_id: ["./photos/10_1_0.jpg", ...]}`.
These relative paths are embedded in the `offlinePhotos` JS variable.

#### `_build_html()` flags (browse offline)
- `offline_data` is set → `OFFLINE_MODE = true`
- `db_only` is **not** set → `DB_ONLY_MODE = false`
- All tabs remain visible; both browse and database views work.

---

### 3b. Database page — `⬇ HTML`

**Location:** Filter row (second line), rightmost export button. Click opens a popup:
- **Without photos** — compact file, 📷 badge still shows on cards that have photos
- **With photos** — photos embedded as data URIs; file can be large for big datasets

**Purpose:** Send a filtered subset of takes (e.g. a specific VFX ID, a shoot day, a bin) to
someone who doesn't have access to the live server. Single file, no folder structure.

#### Client function: `_doExportDbHtml(withPhotos)` (`generate_html.py`)
1. Opens popup via `_openHtmlExportMenu(event)` → user picks without/with photos.
2. Collects `rows = dbRows.filter(dbRowMatches)` — exactly what is on screen.
3. `POST /api/export-db-html` with `{rows, photos: withPhotos}`.
4. Downloads response blob as `database_export.html`.
5. In `OFFLINE_MODE` the function returns immediately (button is hidden anyway).

#### Server endpoint: `POST /api/export-db-html` → `api_export_db_html()` (`server.py`)
```python
rows         = body.get("rows") or []
include_pics = body.get("photos", False)
photos = {}
slate_ids = {r.get("Slate") for r in rows if r.get("Slate")}
for record in db_data.get("records", []):
    sid  = record.get("slateId", "")
    pics = record.get("referencePictures") or []
    if sid in slate_ids and pics:
        # Always register the slate (so 📷 badge appears); embed data only when requested.
        photos[sid] = pics if include_pics else []

html = g._build_html(g.build_data(),
    offline_data={"db_rows": rows, "delivered": [], "photos": photos},
    db_only=True,
)
# Sent as text/html attachment → browser download
```

Photos in the JSON database are already stored as data URIs (`data:image/jpeg;base64,...`),
so no conversion is needed — they are passed through directly into `offlinePhotos`.

#### `_build_html(db_only=True)` flags
| JS constant | Value | Effect |
|---|---|---|
| `OFFLINE_MODE` | `true` | Disables all server calls |
| `DB_ONLY_MODE` | `true` | Forces database view, hides all other UI |

CSS hidden by `.db-only-mode`:
```css
.db-only-mode .tab-bar             { display: none !important; }
.db-only-mode #offline-html-btn    { display: none !important; }
.db-only-mode #offline-html-status { display: none !important; }
.db-only-mode #export-pdf-btn      { display: none !important; }
.db-only-mode #export-html-btn     { display: none !important; }
```

JS at init forces the database view regardless of saved localStorage state:
```js
if (DB_ONLY_MODE) {
    document.body.classList.add('db-only-mode');
    setView('database');
}
```

#### Performance: lazy card rendering
`renderDatabase()` renders **only the title line** for each card. The full details
(`renderDbDetails`) are populated lazily when a card is first expanded via `toggleDbCard`.
This is critical for the with-photos case: without lazy rendering, embedding hundreds of
photos' data URIs into the initial innerHTML of all cards at once would OOM the browser tab.

#### What works / what doesn't in the exported database file

| Feature | Works? | Notes |
|---|---|---|
| Filter fields (Slate, VFX ID, Date…) | ✅ | Pure client-side |
| Sort / group mode buttons | ✅ | Pure client-side |
| Card expand / collapse | ✅ | Lazy-rendered on first expand |
| 📷 badge on folded cards | ✅ | Slate IDs always registered in `offlinePhotos` |
| Reference photos on expand | ✅ (if exported with photos) | Embedded as data URIs |
| Take notes display | ✅ | Embedded in rows as `_note` field |
| CSV export (`⬇ CSV`) | ✅ | Fully client-side |
| PDF export (`⬇ PDF`) | ✗ | Button hidden (requires server) |
| HTML re-export | ✗ | Button hidden (requires server) |
| Save / edit take notes | ✗ | Requires server |
| Edit / Revert / Omit buttons | ✗ | Hidden when `OFFLINE_MODE=true` |
| Bins (create, filter) | ⚠️ | Works locally in that file's localStorage; live-app bins not carried over |
| Bin export (download JSON) | ✅ | Client-side download |
| Bin import (apply notes) | ✗ | Note-save step requires server |
