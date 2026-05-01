# Improvement Ideas — Future Development

Collected ideas for future sessions, ordered roughly by complexity.

---

## 1. Offline Static HTML Export

**What:** A `generate_html.py` mode that produces a fully self-contained HTML
file — no Flask server, no API calls, no `file://` system links.

**How:**
- All shoot data is JSON-embedded in the page (already done for Browse)
- Database CSV rows are also embedded as a JS constant
- Delivered packages manifests are embedded if present
- All interactivity (search, group, sort, fold/unfold, tabs) works client-side
- Cart / Queue / Build are hidden or disabled (read-only mode)
- Single output file, can be sent by email or opened directly in any browser

**Why:** Useful for sharing a snapshot of the shoot data with vendors, directors,
or remote collaborators who don't have access to the server or the volumes.

---

## 2. Block ↔ Database Cross-Reference (with per-block CSV export)

**What:** Link each Browse block to its matching Database (CSV) rows, based on
scene number. Show a clickable badge in Browse. Write a filtered CSV per block.

### Matching logic

- Block directory contains scene tags, e.g. `PJ04__S18__CAST__Desc` → scenes `["S18"]`
- A CSV row matches if the **numeric prefix** of its Slate field equals the scene
  number: slate `"18/2"` → scene `18` → matches `S18`.
- A block with multiple scenes (e.g. `S01_S02`) matches rows for scene 1 OR scene 2.

### Per-block CSV

When parsing directories (or on-demand via a server endpoint), for each block:
1. Extract scene numbers from the directory name.
2. Filter the Database CSV to rows whose slate scene number is in that set.
3. Write matching rows to `{block_path}/__00_Database/{block_name}_db.csv`
   (inside the `__` prefixed dir so sanity check treats it as empty until renamed).

This gives VFX wranglers a per-block reference CSV they can open offline.

### Browse badge

In Browse, next to the subdir pills (`10_Infos`, `20_HDR`, etc.), add:

```
[Slate (N)]
```

Where N = number of matching CSV rows for this block. The badge is only shown
when N > 0.

Clicking the badge:
1. Switches to the Database tab
2. Pre-fills the Slate filter input with the scene number(s) of the block
   (e.g. `"18"` to show slates `18/1`, `18/2`, `18/3` …)
3. Scrolls to the top of the results

**Implementation notes:**
- The match count can be computed client-side at render time if the full DB rows
  are already loaded (cached in `dbRows`). If DB is not yet loaded, clicking
  triggers `loadDatabase()` first, then applies the filter.
- A JS function `scenesToSlateFilter(scenes)` converts `["S18", "S02"]` →
  filter string to pass to `setDbFilter('slate', ...)` or a combined search.
- The badge should use a distinct color (e.g. cyan, matching `.db-vfxid`) to
  visually connect Browse and Database.

---

## 3. Browse ↔ Delivered Cross-Reference

**What:** In Browse, each block shows a small badge if it has been included in
at least one delivered package.

**How:**
- At page load, index delivered packages from `deliveredPackages` (already
  fetched when Delivered tab is visited, or load lazily).
- For each block path, check if any delivered manifest contains a block with
  matching `original_name` or source path.
- Show a badge like `[MPC ✓]` or `[2 deliveries]` on the Browse entry title line.
- Clicking opens Delivered tab filtered to that block name.

---

## 4. Database Stats Bar

**What:** A live stats line below the Database filter row showing counts for the
current filter result.

**Content:** `N takes · M slates · P scenes · Q unique lenses`

**How:** Computed in `renderDatabase()` from the `filtered` array before
rendering cards. Updated on every filter/search change. No server needed.

---

## 5. Database — Export Filtered View as CSV

**What:** A button in the Database controls bar: `⬇ Export CSV`.

**How:**
- Client-side: build a CSV string from `filtered` rows using the current column
  order, trigger a `<a download>` click.
- No server call needed — pure JS `Blob` + `URL.createObjectURL`.

---

## 6. Database — Wrangler Quick Filter

**What:** Two toggle buttons `Clem` and `Quentin` (the two wranglers in the
current dataset) as quick filter chips, complementing the per-field inputs.

**How:** On click, set `dbFilters.wrangler = 'Clem'` (or clear it). The global
`dbRowMatches` already handles this if extended with a `wrangler` filter key.
Wrangler values should be read dynamically from the loaded rows (not hardcoded)
in case the list changes in future CSVs.

---

## 7. Persistent UI State

**What:** Remember active tab, group mode, sort key, sort direction, and search
queries across page reloads.

**How:** Save to `localStorage` on every change; restore on page load before
the first `render()` call. Keys: `vfx_ui_tab`, `vfx_ui_mode`,
`vfx_db_group`, `vfx_db_sort`, `vfx_db_sort_asc`.

Small change, high daily value.

---

## 8. Open in Finder (macOS)

**What:** A button on each Browse entry that opens the block directory directly
in macOS Finder, in addition to the existing "copy path" button.

**How:** Server endpoint `POST /api/open-folder` that calls
`subprocess.run(["open", path])`. The button calls this endpoint with the block
path. Safe: validate the path starts with `DATA_PATH` before opening.

---

## 9. Keyboard Shortcuts

**What:** Power-user shortcuts for faster navigation.

| Shortcut | Action |
|----------|--------|
| `⌘F` / `Ctrl+F` | Focus the active tab's search input |
| `Escape` | Clear active search |
| `1` / `2` / `3` / `4` | Switch to Browse / Database / Queue / Delivered |

**How:** A single `keydown` listener on `document` in JS. Guard against
intercepting shortcuts when user is typing in an input.

---

## 10. Scene Coverage Map

**What:** A visual grid showing all scenes as cells, colored by data status.

**Example:**

```
S01 [HDR ✓ Photos ✓ Video —]
S18 [HDR ✓ Photos — Video ✓]
```

Each cell shows which key data types are present for a scene, across all shoot
days. Color coding: green = present, grey = missing, amber = partial.

**Why:** Immediately shows gaps before a delivery deadline — "we have HDR for
S18 but no photos yet."

**How:** Computed from `data.by_scenes` already available in the page. Rendered
as a new sub-view within Browse, or as a fifth tab. Requires defining which
subdir names map to which "data type" (configurable in `sanity_check.json`).

---

## Priority Suggestion

| Priority | Idea | Effort |
|----------|------|--------|
| High | Block ↔ Database cross-reference (idea 2) | Medium |
| High | Persistent UI state (idea 7) | Low |
| High | Offline HTML export (idea 1) | Medium |
| Medium | Database stats bar (idea 4) | Low |
| Medium | Browse ↔ Delivered badges (idea 3) | Low |
| Medium | Export filtered CSV (idea 5) | Low |
| Medium | Open in Finder (idea 8) | Low |
| Low | Wrangler quick filter (idea 6) | Low |
| Low | Keyboard shortcuts (idea 9) | Low |
| Low | Scene coverage map (idea 10) | High |
