# Delivery Workflow — Architecture & Implementation Guide

Reference document for the full delivery packaging system. Written to allow
future sessions to continue development consistently.

---

## Architecture Overview

```
python server.py --data-path /Volumes/MACGUFF001/POSEIDON/DATA
        ↓
http://127.0.0.1:5000   (Flask, bound to 127.0.0.1 — NOT localhost)
```

The browser opens `http://127.0.0.1:{port}` (not `localhost`) because
Flask 3.x rejects the `Host: localhost` header when bound to `127.0.0.1`.

Two Python files do all the work:

| File | Role |
|------|------|
| `generate_html.py` | Parses shoot data, renders the full HTML page (CSS + JS embedded as one f-string) |
| `server.py` | Flask server; serves the HTML, exposes API endpoints for all write operations |

`generate_html.py` is also usable standalone (`python generate_html.py`) to
produce a static `vfx_shoot_browser.html`.

---

## Config Files

### `{data_path}/__SHOOT_BROWSER/Config/sanity_check.json`
Loaded by `HTMLGenerator._load_config()`. Controls which subdirs are treated as
HDR, nested-flat, count-only, list-files, etc.

### `{data_path}/__SHOOT_BROWSER/Config/delivery_config.json`
```json
{
  "vendors": ["MPC", "RodeoFX", "TheYard", "MacGuff"],
  "default_output_dir": "/Volumes/MACGUFF001/POSEIDON/DELIVERY_PACKAGES"
}
```
Loaded by `HTMLGenerator._load_config()`. Exposed to the browser as:
```js
const deliveryCfg = { vendors: [...], default_output_dir: "..." };
```

---

## Data Flow: Source → Browser

```
HTMLGenerator.parse_directories()
    └── ShootEntry(path, directory_name, day, scenes, code,
                   description, has_data, subdirs, package_note)
            ↓ asdict()
        build_data() → { by_days, by_scenes, by_codes }
            ↓ JSON-embedded in HTML
        const data = { ... };   (JS global in the page)
```

`package_note` on `ShootEntry` is read from
`{block_path}/10_Infos/block_package_infos.txt`
or `{block_path}/__10_Infos/block_package_infos.txt` (fallback when dir is
still prefixed as empty). If found, it pre-fills the Block Note field in the
cart.

`subdirs` is a `List[SubdirSection]`, serialised to:
```json
[{ "name": "20_HDR", "kind": "nested", "children": [...], "count": -1 }, ...]
```

---

## Three-Tab UI

```
📂 Browse  |  📋 Queue  |  ✅ Delivered
```

`setView(view)` switches tabs and:
- `'delivered'` → adds `.delivered-active` to `.container` (green accent theme)
  and calls `loadDelivered()`
- `'queue'` → calls `renderQueue()`
- Removing `.delivered-active` restores the blue accent for Browse/Queue

### Browse tab
Standard entry cards grouped by Day / Scene / Code. Each entry is foldable:
- **Collapsed**: summary pills showing subdir names
- **Expanded**: full `renderSubdirs()` breakdown with file counts

Checkboxes add/remove entries from the **cart**.

---

## Cart → Queue → Build Workflow

### Cart (bottom panel, fixed)
- Appears when ≥1 entry is checked (`body.cart-open`)
- Collapsible (▲/▼); collapsed state only shows the header bar
- Each cart item: block name, remove button, per-block note textarea
- Package-level note textarea (`#package-note-input`)
- Build form: Vendor (combobox from `deliveryCfg.vendors` + custom input),
  Package name, Date (default today), Output directory

**"Save to Queue"** (`saveToQueue()`):
1. Validates form fields
2. Saves a pending package object to `localStorage` key `vfx_queue`
3. Clears the cart for the next package
4. Increments the Queue badge

### Queue tab
- Lists all pending packages from `localStorage`
- **Edit**: restores a pending package back to the cart (warns if any source
  block paths no longer exist on disk)
- **Delete**: removes from queue without building
- **Select all / Build selected**: runs `buildSelected()`, which POSTs each
  selected package to `/api/build-package` sequentially with live progress

### Pending package object (localStorage)
```js
{
  id: Date.now(),           // unique ID
  vendor: "MPC",
  package_name: "poseidon_HDR_batch01",
  date: "2026-04-30",
  output_dir: "/Volumes/.../DELIVERY_PACKAGES",
  package_note: "...",
  blocks: [
    {
      path: "/Volumes/.../DATA/PJ04__S01_S02__CAST_RITZ__Regina_Exterieur",
      delivery_name: "S01_S02__CAST_RITZ__Regina_Exterieur",
      note: "per-block note",
      scenes: ["S01", "S02"],
      code: "CAST_RITZ",
      description: "Regina_Exterieur"
    }, ...
  ]
}
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the browser page (fresh scan every load) |
| GET | `/api/entries` | All shoot entries as JSON |
| POST | `/api/generate-html` | Regenerate static `vfx_shoot_browser.html` |
| POST | `/api/run-sanity-check` | Run `sanity_check.py`, return stdout/stderr |
| POST | `/api/build-package` | Copy blocks, write manifest, write `__packages_infos/` |
| GET | `/api/delivered-packages` | Return all manifests from `__packages_infos/` |

### POST `/api/build-package`

**Request body:**
```json
{
  "vendor": "MPC",
  "package_name": "poseidon_HDR_batch01",
  "date": "2026-04-30",
  "output_dir": "/Volumes/.../DELIVERY_PACKAGES",
  "package_note": "...",
  "blocks": [ { "path": "...", "delivery_name": "...", "note": "...",
                "scenes": [...], "code": "...", "description": "..." } ]
}
```

**Server logic:**
1. Resolves versioned output dir:
   `{output_root}/{vendor}/{YYYYMMDD}_{package_name}/`
   → if exists, appends `_v02`, `_v03`, etc.
2. Detects delivery-name collisions (two blocks with same stripped name)
   → falls back to full original dir name for colliding blocks
3. `shutil.copytree(src, dest, ignore=_ignore_empty_dirs)`:
   - `_ignore_empty_dirs` skips any subdir that contains no visible files
     (uses `os.walk` to check recursively)
4. Writes `block_notes.txt` inside each block dest if note non-empty
5. Computes `subdirs` from the **copied** dest using
   `HTMLGenerator(DATA_PATH).get_subdir_sections(dest)` — serialised with
   `asdict()`. These reflect the actual delivered content.
6. Writes `Package_Infos.txt` at package root if package note non-empty
7. Writes `package_manifest.json` at package root
8. Writes `{output_root}/__packages_infos/{pkg_dir_name}.json`
   (same content — used by the Delivered tab summary)

**Output directory structure:**
```
{output_root}/
├── __packages_infos/
│   └── 20260430_poseidon_HDR_batch01.json
└── MPC/
    └── 20260430_poseidon_HDR_batch01/
        ├── package_manifest.json
        ├── Package_Infos.txt          (only if package note non-empty)
        ├── S01_S02__CAST_RITZ__Regina_Exterieur/
        │   ├── block_notes.txt        (only if block note non-empty)
        │   ├── 20_HDR/
        │   └── ...
        └── ...
```

### GET `/api/delivered-packages`

Reads `default_output_dir` from `delivery_config.json`, then returns all
`*.json` from `{output_dir}/__packages_infos/`, sorted newest-first.

---

## package_manifest.json Structure

```json
{
  "vendor": "MPC",
  "package_name": "poseidon_HDR_batch01",
  "date": "20260430",
  "version": 1,
  "timestamp": "2026-04-30T14:32:00",
  "created_by": "vfx_shoot_browser",
  "source_data_path": "/Volumes/.../DATA",
  "output_path": "/Volumes/.../DELIVERY_PACKAGES/MPC/20260430_poseidon_HDR_batch01",
  "package_note": "...",
  "blocks": [
    {
      "original_name": "PJ04__S01_S02__CAST_RITZ__Regina_Exterieur",
      "delivery_name": "S01_S02__CAST_RITZ__Regina_Exterieur",
      "note": "per-block note",
      "scenes": ["S01", "S02"],
      "code": "CAST_RITZ",
      "description": "Regina_Exterieur",
      "subdirs": [
        { "name": "20_HDR", "kind": "nested",
          "children": [{"name": "Fisheye", "count": 12}], "count": -1 },
        ...
      ]
    }
  ]
}
```

`subdirs` is populated at build time from the actual copied directory, so it
always reflects what was delivered (not the source at a later date).

---

## Delivered Packages Tab

Green accent theme (`.delivered-active` on `.container` overrides `--accent`
to `#4ac26b`). The cart panel is **outside** `.container` so it keeps the blue
accent.

### Controls bar
Group-by buttons: By Vendor / By Date / By Scene / By Code + search input.
Same layout as Browse controls.

### Rendering
`renderDelivered()` groups `deliveredPackages` by the selected key, sorted
descending (newest first for dates). Each group uses the standard `.group-header`
+ `.group-count` style.

Each package renders as a `.del-entry` card:
- **Header row**: vendor badge (blue), package name badge (green), date badge
  (amber), optional version pill (purple), block count, timestamp
- **Block entries**: each block is a foldable `.entry` card (same CSS as Browse)
  - **Collapsed**: `del-block-name` + scene/code badges + summary pills
    (subdir names from `b.subdirs`)
  - **Expanded**: full `renderSubdirs(b.subdirs)` breakdown with file counts

Block expand state is tracked in `expandedDelBlocks` (a `Set`). Toggled by
`toggleDelBlock(btn)`, which reads `entry.dataset.delBlockId`.

### Search
`pkgMatches(pkg, q)` searches across: vendor, package name, date, package note,
all block delivery names, block notes, scenes, codes, descriptions.

---

## Key Technical Patterns

### F-string escaping in `generate_html.py`
The entire HTML/CSS/JS is one Python f-string. Rules:
- `{{` / `}}` → literal `{` / `}` in JS/CSS
- `${{...}}` → JS template literal `${...}`
- `({{ key, value }})` → JS destructuring `({ key, value })`
- Never use Python variables inside JS object literals — always build the
  string outside and interpolate the result

### HTML attribute safety — `dataset.path` pattern
Never use `JSON.stringify(path)` inside an `onclick="..."` attribute — the
double quotes from JSON.stringify will end the HTML attribute early.

**Correct pattern:**
```html
<div class="entry" data-path="${escHtml(entry.path)}">
    <button onclick="doSomething(this.closest('.entry').dataset.path)">
```
Use `this.closest('[data-path]').dataset.path` in all onclick handlers that
need the block path.

### Cart state (localStorage keys)
| Key | Content |
|-----|---------|
| `vfx_cart` | `{ [path]: { path, delivery_name, note, scenes, code, description } }` |
| `vfx_queue` | Array of pending package objects (see above) |
| `vfx_package_note` | Current package-level note string |
| `vfx_build_form` | `{ vendor, package_name, date, output_dir }` |

---

## What Has NOT Been Done Yet (Future Work)

- **Testing the Delivered tab** against real built packages (not yet validated
  in production — the subdirs feature was added but not yet approved)
- **Global packages log** at `{data_path}/__SHOOT_BROWSER/packages_log.json`
  (mentioned in PACKAGING_ROADMAP.md, not implemented)
- **Delivery history / re-delivery tracking** per package
- **PyInstaller bundle** for double-click executable
- **Windows path support** (pathlib handles separators but untested)
