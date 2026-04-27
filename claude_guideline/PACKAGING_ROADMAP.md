# Vendor Packaging — Development Roadmap

## Context

The goal is to add a **delivery packaging** feature to the tool:
select a set of shoot-day blocks, define package metadata, and copy the
relevant data to a local delivery directory. The browser (HTML) is the UI;
a local Python web server is the backend.

This document is the plan for a future development session.

---

## Architecture: local web server

Replace the current static-file workflow with a tiny local server:

```
python server.py        ← single command to start everything
     ↓
http://localhost:5000   ← opens in any browser, any OS
```

**Why Flask (recommended library):**
- Minimal, no external framework overhead
- Runs identically on Windows / Linux / macOS
- Single file to start with (`server.py`)
- Can be bundled later with PyInstaller into a double-click executable

**Server responsibilities:**
- Serve the HTML browser page
- Expose API endpoints for: running sanity check, regenerating HTML, building packages
- Handle all file I/O (copy directories, write notes, write manifests)

**Browser responsibilities:**
- Everything it does now (browse, search, fold/unfold)
- Cart management (localStorage for persistence)
- Package form (vendor, name, date, output dir, notes)
- Display results from server API calls

---

## Step 2 — Minimal server foundation

File: `server.py`

Endpoints to implement first:
```
GET  /                         → serve the browser HTML
POST /api/run-sanity-check     → run sanity_check.py, stream output
POST /api/generate-html        → regenerate vfx_shoot_browser.html
GET  /api/entries              → return parsed shoot entries as JSON
```

The browser HTML is served dynamically (no more static file to open).
The data JSON is fetched from `/api/entries` instead of being embedded.

Config file (`sanity_check.json`) is read by the server at startup —
no path changes needed.

---

## Step 3 — Cart UI in the browser

Each entry block gets a **checkbox** (top-left corner, visible on hover).

A **cart panel** appears at the bottom or as a sidebar when at least one
block is selected. It shows:
- Selected block names (delivery names, day prefix stripped)
- Per-block note field (plain text, optional)
- "Remove" button per block
- Total block count

Cart state is stored in `localStorage` so it survives page refresh and
mode changes (By Days / By Scenes / By Codes).

**Delivery name collision warning:** if two selected blocks would produce
the same delivery name after stripping the day prefix, show a warning
inline in the cart. The sanity check already detects this globally;
the cart should detect it for the current selection specifically.

---

## Step 4 — Package builder

### Package form (in the browser)

Fields:
| Field | Notes |
|-------|-------|
| Vendor | Free text (e.g. "MPC", "ILM") |
| Package name | Becomes the folder name — alphanumeric + hyphens only |
| Date | Defaults to today (YYYY-MM-DD) |
| Output directory | Typed or browsed — must exist |
| Package notes | Plain text, written to `package_notes.txt` |

### Versioning

Each delivery of the same package name gets a version suffix:
`{package_name}_v01`, `_v02`, etc.

The server checks if the target folder already exists and auto-increments.
This handles re-deliveries cleanly without overwriting past packages.

### Output structure

```
{output_dir}/
└── {vendor}/
    └── {package_name}_v01/
        ├── package_manifest.json     ← metadata (see below)
        ├── package_notes.txt         ← package-level notes
        ├── S01_S02__CAST_RITZ__Regina_Exterieur/
        │   ├── block_notes.txt       ← only if notes were added
        │   ├── 20_HDR/
        │   ├── 32_Photog_Photos/
        │   ├── 40_Photos/
        │   └── ...                   ← full block content, day prefix stripped
        └── S19_S20__PORT__Montparnasse_Exterieur/
            └── ...
```

**Day prefix stripping rule:**
- Strip `JXX__` or `PJXX__` from the directory name
- If two blocks produce the same stripped name → keep the full name
  (collision already flagged by sanity check and cart UI)

### package_manifest.json structure

```json
{
  "vendor": "MPC",
  "package_name": "poseidon_HDR_batch01",
  "date": "2026-04-27",
  "version": 1,
  "created_by": "system",
  "source_data_path": "/Volumes/MACGUFF001/POSEIDON/DATA_rename",
  "output_path": "/path/to/delivery/MPC/poseidon_HDR_batch01_v01",
  "blocks": [
    {
      "original_name": "PJ04__S01_S02__CAST_RITZ__Regina_Exterieur",
      "delivery_name": "S01_S02__CAST_RITZ__Regina_Exterieur",
      "note": "Optional per-block note text"
    }
  ],
  "delivery_history": [
    { "version": 1, "date": "2026-04-27", "note": "" }
  ]
}
```

### Server endpoint

```
POST /api/build-package
Body: { vendor, package_name, date, output_dir, notes, blocks: [...] }
Response: { success, output_path, version, errors: [...] }
```

The server:
1. Resolves version number
2. Creates output directory structure
3. Copies each block directory (full copy, day prefix stripped)
4. Writes `block_notes.txt` per block if note present
5. Writes `package_notes.txt`
6. Writes `package_manifest.json`
7. Returns result to browser

---

## Step 5 — Notes writing

Notes are plain `.txt` files written during package build.

- **Package note** → `{package_root}/package_notes.txt`
- **Block note** → `{package_root}/{delivery_name}/block_notes.txt`

Notes are only written if non-empty. No note = no file created.

---

## Package tracking / history

A global log file at:
```
{data_path}/__SHOOT_BROWSER/packages_log.json
```

Every successful build appends an entry:
```json
{
  "timestamp": "2026-04-27T14:32:00",
  "vendor": "MPC",
  "package_name": "poseidon_HDR_batch01",
  "version": 1,
  "output_path": "...",
  "block_count": 5
}
```

This allows future reporting: "what did we send to whom and when."

---

## Cross-platform notes

| Concern | Status |
|---------|--------|
| Path separators | `pathlib.Path` handles this — no changes needed |
| Hardcoded `/Volumes/...` | Must be removed — data root fully from config or CLI arg |
| `execCommand` clipboard | Works in all browsers on file:// — already implemented |
| Python deps | Flask is the only new dependency — `pip install flask` |
| Packaging as executable | PyInstaller bundles Flask + scripts — future step |

**Windows-specific:** network paths use `\\server\share` format.
`pathlib.Path` handles these correctly. No special treatment needed.

---

## Suggested implementation order

1. `server.py` — minimal Flask server serving current HTML, `/api/entries` endpoint
2. Cart UI — checkboxes + cart panel in the browser
3. Package form — vendor / name / date / output / notes fields
4. `/api/build-package` endpoint — copy logic + manifest writing
5. Global packages log
6. Re-delivery / versioning polish
