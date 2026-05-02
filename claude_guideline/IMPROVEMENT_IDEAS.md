# Improvement Ideas — Future Development

Collected ideas for future sessions, ordered roughly by complexity.

---

## 1. ✅ Offline Static HTML Export

**Status: Done.**

`generate_offline_html()` embeds all shoot data, database CSV rows, and delivered
package manifests into a single self-contained HTML file. Cart, Queue, and all
write actions are hidden. A purple banner marks the file as read-only.

- CLI: `python generate_html.py --offline`
- Server: `POST /api/generate-offline-html`
- Browser button: **💾 Offline HTML** in the Browse controls bar

---

## 2. ✅ Block ↔ Database Cross-Reference

**Status: Done.**

- Per-block slate CSVs extracted to `00_Database/slates_YYYY-MM-DD.csv` via
  `POST /api/extract-slates` (button: **📊 Extract Slates** in Browse controls).
- Plate day slates (`PJ` prefix) matched as `P<N>` keys to avoid cross-contamination
  with same-numbered regular scenes.
- `Slates (N)` badge shown in collapsed Browse entries alongside subdir pills.
- Clicking the badge switches to the Database tab filtered to that block's scenes
  via a dismissible pin banner.
- Extraction log written to `__SHOOT_BROWSER/Log/extract_slates_YYYY-MM-DD_HHMM.log`
  with skipped blocks, unmatched CSV keys, and per-block counts.

---

## 3. ✅ Browse ↔ Delivered Cross-Reference

**Status: Done.**

Delivered packages are fetched silently in the background on page load.
Each Browse entry that has been delivered shows small vendor badges (e.g. `MPC`)
to the right of the description. Clicking a badge switches to the Delivered tab
grouped by vendor with that vendor pre-filled in the search.

---

## 4. ✅ Database Stats Bar

**Status: Done.**

Live stats shown inline at the right end of the Database controls bar:
`N takes · M slates · P scenes · Q lenses · R days`. Updates on every filter change.

---

## 5. Database — Export Filtered View as CSV

**What:** A button in the Database controls bar: `⬇ Export CSV`.

**How:**
- Client-side: build a CSV string from `filtered` rows using the current column
  order, trigger a `<a download>` click.
- No server call needed — pure JS `Blob` + `URL.createObjectURL`.

---

## 6. Database — Wrangler Quick Filter

**What:** Toggle chips for wrangler names as quick filter, complementing the
per-field inputs.

**How:** On click, set `dbFilters.wrangler = 'name'` (or clear it). The global
`dbRowMatches` already handles this if extended with a `wrangler` filter key.
Wrangler values should be read dynamically from the loaded rows (not hardcoded)
in case the list changes in future CSVs.

---

## 7. ✅ Persistent UI State

**Status: Done.**

Active tab, browse/database/delivered group mode, sort key, sort direction,
all search queries, and all per-field database filters (Slate, VFX ID, Date,
Shoot Day, Roll, Lens, Focal) are saved to `localStorage` key `vfx_ui_state`
on every change and restored before the first `render()` call.

---

## 8. ✅ Open in File Manager (cross-platform)

**Status: Done.**

- `POST /api/open-folder` endpoint dispatches `open` / `explorer` / `xdg-open`
  for macOS / Windows / Linux. Path validated against `DATA_PATH`.
- House-icon button on each Browse entry title line.
- Subdir badges (`20_HDR`, `10_Infos`, etc.) in the collapsed summary are also
  clickable and open the specific subdirectory directly.

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

## Status Summary

| # | Idea | Status | Effort |
|---|------|--------|--------|
| 1 | Offline HTML export | ✅ Done | Medium |
| 2 | Block ↔ Database cross-reference | ✅ Done | Medium |
| 3 | Browse ↔ Delivered badges | ✅ Done | Low |
| 4 | Database stats bar | ✅ Done | Low |
| 5 | Export filtered CSV | ⬜ Todo | Low |
| 6 | Wrangler quick filter | ⬜ Todo | Low |
| 7 | Persistent UI state | ✅ Done | Low |
| 8 | Open in file manager | ✅ Done | Low |
| 9 | Keyboard shortcuts | ⬜ Todo | Low |
| 10 | Scene coverage map | ⬜ Todo | High |
