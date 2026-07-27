# Export System — Complete Reference

This document covers every export entry point in the application: what triggers it, what
scope of data it uses, whether the file is downloaded to the user's machine or saved to disk
on the server, and how to extend each path.

For detailed PDF generation internals (ReportLab layout, column weights, page structure) see
`EXPORT_CSV_PDF.md`, which remains valid for those specifics.

---

## 1. Entry points at a glance

There are **two `⬇ Export` menus** in the application — one on each page.

### Database page — `⬇ Export` button (`db-export-menu-btn`)

Opens `_openDbExportMenu(e)`. Operates on **currently filtered rows** (`dbRows.filter(dbRowMatches)`).

```
⬇ CSV
⬇ PDF
⬇ HTML — Without photos
⬇ HTML — With photos
───────────────────────
⬇ Export All Files…
```

Hidden entirely in `OFFLINE_MODE`.

### Browse page — `⬇ Export` button (`offline-export-menu-btn`)

Opens `_openOfflineExportMenu(e)`. Operates on **all rows** (the whole database).

```
💾 Global Offline HTML
───────────────────────
⬇ Global .csv
⬇ Global .pdf
───────────────────────
⬇ All…
```

Hidden in `offline-mode` (CSS) and in `db-only-mode` (CSS).

### Extract Slates menu — `📊 Extract Slates` button (`extract-slates-btn`)

A separate flow (not discussed in depth here) for writing CSV/PDF/HTML files
directly into each Browse block's `00_Database/` folder. It reuses the same
CSV and PDF modals via `_csvExtractMode` and `_pdfExtractMode` flags.

---

## 2. Mode flags

Four boolean flags control which code path runs inside shared functions:

| Flag | Where set | Where reset | Effect |
|---|---|---|---|
| `_globalExportMode` | `_openGlobalCsvModal()` / `_openGlobalPdfModal()` | `closeCsvExportModal()` / `closePdfExportModal()` | `_doExportCsv` and `_doPdfExport` use `[...dbRows]` (all rows) instead of `dbRows.filter(dbRowMatches)`. CSV modal title becomes "Global Export — CSV"; PDF modal title becomes "Global Export — PDF". |
| `_csvExtractMode` | `openCsvExportModal(true)` | reset in the extract flow's `finally` | CSV modal title becomes "Extract Slates — CSV"; changes the export button label. |
| `_pdfExtractMode` | `openPdfExportModal(true)` | reset in the extract flow's `finally` | Changes PDF modal title and export button. |
| `OFFLINE_MODE` | Set at JS startup from `const OFFLINE_MODE = ...` embedded by Python | Never — read-only at runtime | Hides all export buttons, prevents server calls in `_doExportCsv`/`_doPdfExport`. |

**Rule:** `_globalExportMode`, `_csvExtractMode`, `_pdfExtractMode` are always `false` by default.
Set one of them, open the modal, the modal's close path resets it. They are never true simultaneously.

---

## 3. CSV export

### Client-only — no server call

```
openCsvExportModal()          ← from DB page menu (normal) or Browse menu (global)
  └─ _renderCsvModal()        ← builds UI: preset selector, col checklist, sort row
       └─ user clicks Export
            └─ _doExportCsv() ← builds blob, downloads, closes modal
```

`_doExportCsv(downloadName?)`:
1. Lazy-init `csvModalCols` if empty.
2. Read sort key from `#csv-sort-key` DOM element (only when no `downloadName` — i.e., called from modal).
3. **Row selection:**
   - `_globalExportMode = true` → `[...dbRows]` (all rows)
   - otherwise → `dbRows.filter(dbRowMatches)` (filtered rows)
4. Sort, keep only `c.on === true` columns.
5. Build CSV string, create `Blob`, trigger `<a>.click()`.
6. If no `downloadName`: close modal (which also resets `_globalExportMode`).

### Preset storage

Presets are persisted to the **server disk** via `/api/ui-presets/csv_presets` (POST/GET).
They are also held in the `csvPresets` JS object for the session.

```js
// Snapshot
_csvCurrentConfig()  →  { cols: [...csvModalCols], sortKey, sortAsc }

// Apply
_csvApplyConfig(cfg)  // guards: only overrides cols if cfg.cols.length > 0
```

---

## 4. PDF export

### Client modal + server PDF generation

```
openPdfExportModal()          ← from DB page menu (normal) or Browse menu (global)
  └─ _renderPdfModal()        ← builds UI: preset selector, scope, orientation, sort, col pickers
       └─ user clicks Export PDF
            └─ _doPdfExport() ← collects config, POST /api/export-pdf, downloads blob
```

`_doPdfExport(downloadName?)`:
1. Lazy-init `pdfInfoCols` / `pdfTakeCols` if empty.
2. **Row selection:**
   - `_globalExportMode = true` → `[...dbRows]`
   - otherwise → `dbRows.filter(dbRowMatches)`
3. Derive unique `slateIds` in sort order; build `takeIds` if `pdfScope === 'filtered'`.
4. If no `downloadName`: close modal (resets `_globalExportMode`).
5. `POST /api/export-pdf` with:
   ```json
   { "slates": [...], "take_ids": null|[...], "info_fields": [...],
     "take_cols": [...], "show_vfx_work": true, "show_notes": true, "landscape": true }
   ```
6. Download response blob.

**Server (`api_export_pdf`):** loads DB, builds `slate_rows` dict, calls `_generate_pdf(buf, ...)`,
streams as `application/pdf`. See `EXPORT_CSV_PDF.md` §2 for full layout details.

### Preset storage

Same mechanism as CSV: server disk via `/api/ui-presets/pdf_presets`.

```js
_pdfCurrentConfig()  →  { scope, sortKey, sortAsc, landscape, infoCols, takeCols, showVfxWork, showNotes }
_pdfApplyConfig(cfg) // guards infoCols and takeCols for non-empty
```

---

## 5. DB HTML export

### Client → server → browser download

Available only on the **Database page**, in normal (non-offline) mode.

```
_doExportDbHtml(withPhotos, downloadName?)
  └─ POST /api/export-db-html  { rows: [...filtered rows], photos: true|false }
       └─ server calls g._build_html(..., offline_data=..., db_only=True)
            └─ response is text/html attachment → browser download
```

- **Scope:** `dbRows.filter(dbRowMatches)` — always the filtered view.
- **Photos:** if `withPhotos=true`, reference pictures (already base64 data URIs in the JSON DB)
  are passed through into `offlinePhotos`. If false, photos are registered (so the 📷 badge shows)
  but the data is empty (`[]`).
- **Result flags:** `OFFLINE_MODE=true`, `DB_ONLY_MODE=true` — the HTML shows only the Database view.
- **Output:** single self-contained `.html` file (everything inline).

---

## 6. Offline HTML export — full-app snapshot

Saves to `{default_output_dir}/GLOBAL/Offline/` on server disk. Opens result in a new browser tab.

### Trigger

From the Browse page `⬇ Export` menu → **💾 Global Offline HTML** → `generateOfflineHtml()`.

```
generateOfflineHtml()
  └─ window.open('', '_blank')   ← must happen before any await (popup blocker context)
  └─ POST /api/generate-offline-html
       └─ g.generate_offline_html(lidar_entries, assets_data, assets_shoot_dir)
            └─ archives previous GLOBAL/Offline/ export → history/
            └─ copies Lidar preview PNGs → lidar_previews/ subfolder
            └─ builds HTML (all tabs, all data)
            └─ writes vfx_shoot_browser_offline.html
            └─ writes exported_YYYY-MM-DD_HH-MM.txt marker
  └─ new tab navigates to /offline-site/vfx_shoot_browser_offline.html
```

### `generate_offline_html()` in detail (`generate_html.py`)

Parameters:
- `output_path` — if provided (CLI use), writes directly there, no history management.
- `lidar_entries` — list of Lidar entry dicts from `_parse_lidar_assets()`.
- `assets_data` — list of asset dicts from `_parse_assets_shoot()`.
- `assets_shoot_dir` — path to `ASSETS_SHOOT_DIR`; required to copy Lidar preview PNGs.

Steps:
1. Resolve `export_dir = GLOBAL/Offline/`.
2. Archive previous export: `_archive_previous_offline_export(export_dir)`.
3. Copy Lidar preview PNGs: `_copy_lidar_previews(entries, export_dir, assets_shoot_dir)`.
   - Copies `ASSETS_SHOOT_DIR/rel_path/preview.png` → `export_dir/lidar_previews/rel_path/preview.png`.
   - Rewrites paths in entries to `./lidar_previews/rel_path/preview.png` (relative).
4. Build `offline_data` dict (db_rows, delivered, photos, lidar_entries, assets_data).
5. Call `_build_html(build_data(), offline_data=offline_data)` → write HTML file.
6. Write `exported_YYYY-MM-DD_HH-MM.txt` marker.

### History management — `_archive_previous_offline_export(export_dir)`

```
GLOBAL/Offline/
  vfx_shoot_browser_offline.html
  lidar_previews/
  exported_2026-07-21_10-30.txt
  history/
    exported_2026-07-21_10-30/
      vfx_shoot_browser_offline.html
      lidar_previews/
      exported_2026-07-21_10-30.txt
```

Logic:
1. Glob `exported_*.txt` in `export_dir`.
2. If none → nothing to archive (first export).
3. Take `markers[0].stem` as `archive_name`.
4. Create `history/archive_name/`.
5. Move every item except `.` files and `history/` into that subdir.

`._` macOS AppleDouble files on external drives are skipped by the `item.name.startswith('.')`
guard to prevent `FileNotFoundError` (they disappear before `shutil.move` runs).

### `OFFLINE_MODE` in the exported HTML

`_build_html()` sets `const OFFLINE_MODE = true` when `offline_data is not None`.
At startup the JS adds `offline-mode` to `document.body`, which hides:
- `#tab-queue`, `#tab-delivered`
- `#cart-panel`, `.entry-cb`, `.asset-cb`, `.finder-btn`, `.vendor-badge`
- `#extract-slates-btn`, `#extract-status`
- `#offline-export-menu-btn`, `#offline-export-status`

Lidar/Assets pages load from `offlineLidarEntries` / `offlineAssetsData` JS constants instead
of API calls. Photo lightbox uses `./lidar_previews/...` relative URLs for Lidar thumbnails.

---

## 7. Global Export All — `⬇ All…`

Saves CSV + PDF to `GLOBAL/Database/` and offline HTML to `GLOBAL/Offline/` (each with independent
history). No file is downloaded to the user's machine.

### Trigger

Browse page `⬇ Export` menu → **⬇ All…** → `_openGlobalExportAllModal()` → preset modal →
user clicks **Export All** → `_doGlobalExportAll()`.

### Preset modal (`global-export-all-overlay`)

```
Global Export All
CSV · PDF · Offline HTML saved to GLOBAL/Database/ and GLOBAL/Offline/.

CSV preset:  [— current settings —  ▾]
PDF preset:  [— current settings —  ▾]

[Cancel]  [Export All]
```

Reuses `.export-all-*` CSS classes. Preset selectors populated by `_loadCsvPresets()` /
`_loadPdfPresets()` calls.

### `_doGlobalExportAll()` sequence

1. Read preset selections from modal DOM.
2. Lazy-init CSV/PDF column defaults.
3. Apply selected presets via `_csvApplyConfig` / `_pdfApplyConfig`.
4. Close modal.
5. Disable `#offline-export-menu-btn`, show `⏳ Exporting…`.
6. Build `csvCols` from `csvModalCols.filter(c => c.on)`.
7. Snapshot PDF config via `_pdfCurrentConfig()`, extract `info_fields` / `take_cols`.
8. `POST /api/global-export-all` with:
   ```json
   {
     "csv_cols":     ["Slate", "Take", ...],
     "csv_sort_key": "Slate",
     "csv_sort_asc": true,
     "pdf": {
       "info_fields": [...], "take_cols": [...],
       "show_vfx_work": true, "show_notes": true, "landscape": true
     }
   }
   ```
9. Show `✓ Saved` on success, `✗ error` on failure.
10. Re-enable button (in `finally`).

### Server endpoint: `POST /api/global-export-all` → `api_global_export_all()` (`server.py`)

1. Resolve `db_dir = default_output_dir / GLOBAL / Database`.
2. Archive previous contents: `_archive_previous_global_export(db_dir)` (same logic as
   offline HTML's archive — see §6 above).
3. Generate CSV via `g._generate_db_csv(csv_cols, csv_sort_key, csv_sort_asc)`:
   - Calls `_load_offline_db_rows()` (all rows from JSON DB).
   - Sorts and extracts requested columns.
   - Returns UTF-8 BOM bytes (Excel-compatible).
   - Saved as `db_dir/global_database.csv`.
4. Generate PDF: load full DB, collect all unique `slate_ids`, call `_generate_pdf(buf, ...)`.
   - Saved as `db_dir/global_database.pdf`.
5. Write `exported_YYYY-MM-DD_HH-MM.txt` marker in `db_dir`.
6. Call `g.generate_offline_html(lidar_entries, assets_data, assets_shoot_dir)` to also
   refresh `GLOBAL/Offline/` (with its own history management).
7. Return `{"success": true, "path": str(db_dir)}`.

### GLOBAL/Database/ directory layout

```
GLOBAL/Database/
  global_database.csv
  global_database.pdf
  exported_2026-07-27_14-42.txt
  history/
    exported_2026-07-21_10-30/
      global_database.csv
      global_database.pdf
      exported_2026-07-21_10-30.txt
```

---

## 8. Export All Files (DB page)

Covered in `EXPORT_CSV_PDF.md` §4. Key difference from Global Export All:

| | DB page — Export All Files | Browse page — All… |
|---|---|---|
| Scope | Filtered rows | All rows |
| Output destination | Browser downloads | Server disk (`GLOBAL/`) |
| HTML included | Optional (downloaded) | Always (offline HTML to `GLOBAL/Offline/`) |
| README.pdf | Always generated | Not generated |
| Bin export | Optional (JSON download) | Not included |
| History versioning | None (overwrites each run) | Yes |

---

## 9. Preset system

Presets for CSV and PDF are stored **on server disk** (not localStorage) via two REST endpoints:

```
GET  /api/ui-presets/csv_presets   → { "preset_<ts>": {id, name, cols, sort}, ... }
POST /api/ui-presets/csv_presets   ← same shape → saved to disk
GET  /api/ui-presets/pdf_presets   → { "preset_<ts>": {id, name, ...}, ... }
POST /api/ui-presets/pdf_presets   ← same shape → saved to disk
```

Preset files live in the config directory alongside `delivery_config.json`.
This means presets are shared across all browser sessions on the same machine.

**Preset ID format:** `preset_<unix_timestamp_ms>` — never reused, never sorted by date.

**Defensive apply rule:** `_csvApplyConfig` / `_pdfApplyConfig` only override column arrays when
the preset's array is non-empty. This prevents wiping freshly-initialised defaults when a preset
was saved before the modal was ever opened.

---

## 10. The `downloadName` pattern

`_doExportCsv(downloadName?)`, `_doPdfExport(downloadName?)`, `_doExportDbHtml(withPhotos, downloadName?)`
all accept an optional filename:

| Called from | `downloadName` | DOM reads | Alerts | Closes modal |
|---|---|---|---|---|
| Its own modal button | `undefined` | Yes (reads live values) | Yes | Yes |
| Export All sequence | `"base_name.ext"` | No | No | No |

The `downloadName` path must never rely on modal DOM elements being present.

---

## 11. File destinations summary

| Export | Destination | Format |
|---|---|---|
| CSV (DB or Global .csv) | Browser download | `.csv` file |
| PDF (DB or Global .pdf) | Browser download | `.pdf` file |
| DB HTML | Browser download | Single `.html` with inline base64 photos |
| Global Offline HTML | `GLOBAL/Offline/` on server + new browser tab | `vfx_shoot_browser_offline.html` + `lidar_previews/` folder |
| Global Export All — CSV | `GLOBAL/Database/` on server | `global_database.csv` |
| Global Export All — PDF | `GLOBAL/Database/` on server | `global_database.pdf` |
| Global Export All — HTML | `GLOBAL/Offline/` on server | Same as Global Offline HTML |

`GLOBAL/` lives inside `default_output_dir` from `delivery_config.json`.

---

## 12. Important implementation notes

### f-string / JS quoting rules (all JS is inside Python f-strings)

- `{{` / `}}` → literal `{` / `}` in JS output.
- `${{var}}` → `${var}` (JS template literal).
- Never use `\'` — use `&#39;` for single quotes in HTML attributes.
- Never use bare `\n` in JS strings — use `\\n`.

### Adding a new item to the Browse `⬇ Export` menu

1. Add a `<button>` line in `_openOfflineExportMenu` → `menu.innerHTML`.
2. If it opens a modal: create `_openGlobalXxxModal()` that sets any needed mode flags.
3. If it saves to disk: add a server route, add an archive helper if needed.
4. If it hides in offline/db-only mode, ensure the button's container (`#offline-export-menu-btn`)
   is already hidden — no extra CSS needed.

### Adding a new item to the DB `⬇ Export` menu

1. Add a `<button>` line inside `_openDbExportMenu` → `items +=`.
2. Wrap in `if (!OFFLINE_MODE) { ... }` if the action requires a server call.

### Adding a new export format (CSV/PDF variant)

- Client: create a new modal or reuse existing ones with a new mode flag.
- Server: add a route; reuse `_load_db_json()` → `_denormalize_json_to_rows()` →
  `_apply_overrides()` → `_apply_notes()` → `_apply_shared_notes()` to get full rows.
- If saving to disk: follow the `_archive_previous_*` pattern for history management.

### Lidar previews in offline HTML

`_copy_lidar_previews(entries, export_dir, assets_root)` in `HTMLGenerator`:
- Deep-copies each entry.
- Copies PNG files from `ASSETS_SHOOT_DIR/rel_path/preview.png` → `export_dir/lidar_previews/rel_path/preview.png`.
- Rewrites `entry.previews` paths to `./lidar_previews/rel_path/preview.png`.

`renderLidarCard` and `openLidarLightbox` in JS detect the `./` prefix to use relative paths
instead of the `/api/asset-preview/` route. This means Lidar thumbnails and lightbox work in
the offline HTML when the `lidar_previews/` subfolder is present alongside the HTML file.
