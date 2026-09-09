# Take Extras — Shot Name & Parent / Children Takes

User-authored per-take fields shown at the top of every expanded Database card:

| Field | Type | Stored | Derived |
|---|---|---|---|
| **Shot Name** | free string | yes | — |
| **Parent Take** | one take key | yes (`parent_take`) | `_parent_take_label` |
| **Children Takes** | many take keys | no | reverse lookup of `parent_take` |

A take has **at most one parent** and **any number of children**. The link is
edited from either side (set my parent from the child card, or add a child from
the parent card). Both write the same single field: `parent_take` on the child.

**The source database JSON is never modified.** Everything lives in one sidecar
file, exactly like `notes.json` / `shared_notes.json` / `overrides.json`.

---

## 1. Storage

File: `{DATA_DIR}/__DATABASE/take_extras.json`

```json
{
  "version": 1,
  "takes": {
    "<record_id>::<take_id>": {
      "shot_name": "SH_010_020",
      "parent_take": "<record_id>::<take_id>"
    }
  }
}
```

- **Key** = `_override_key` = `f"{_record_id}::{_take_id}"`, stamped onto every
  row by `_apply_overrides()` — which **must run before** `_apply_take_extras()`
  (server.py) / step 4 of `HTMLGenerator._apply_overlays()` (generate_html.py).
- An entry only holds the sub-keys that are set. When both are cleared the whole
  entry is deleted (never left as `{}`).
- `take_extras.json` is in `_DB_JSON_EXCLUDED` (server.py) so it is never loaded
  as source database data.
- **Legacy:** the first cut of this feature wrote `linked_take` instead of
  `parent_take`. Reads still accept it (`_extras_parent()` falls back), and any
  write of that entry rewrites it as `parent_take`.

---

## 2. Server (`server.py`)

### Helpers

| Function | Purpose |
|---|---|
| `_take_extras_path()` | `{DATA_DIR}/__DATABASE/take_extras.json` |
| `_load_take_extras()` | → `{"version": 1, "takes": {}}` on any error |
| `_save_take_extras(x)` | pretty JSON, `ensure_ascii=False` |
| `_extras_parent(ext)` | parent key from an entry, accepts legacy `linked_take` |
| `_take_label(row)` | `"Slate <slate>/T<take> · Roll <roll>"` — badge / picker text |
| `_apply_take_extras(rows, extras)` | annotate rows (below) |
| `_would_cycle(takes, child, new_parent)` | walk the parent chain, detect loops |

### `_apply_take_extras(rows, extras)` — row annotations

Runs one pass to read `shot_name` / `parent_take` and build a
`parent → [child keys]` index, then a second pass to resolve labels:

| Row field | Value |
|---|---|
| `_shot_name` | string (`''` if unset) |
| `_parent_take` | parent's `_override_key` (`''` if none) |
| `_parent_take_label` | `_take_label()` of the parent row, or `''` |
| `_children_takes` | `[{ "key": <override_key>, "label": <take_label> }, …]`, sorted by label |

All fields are `_`-prefixed, so they never leak into CSV `default_cols`
(`[f for f in row if not f.startswith("_")]`).

### Endpoint — `POST /api/take-extras/save`

Body: `{ "key": <override_key>, "shot_name"?: str, "parent_take"?: str }`

**Merge semantics** — only the sub-keys *present in the body* are touched:

- `shot_name` present → set (trimmed) or, if empty, removed.
- `parent_take` (or `linked_take`) present → set or, if empty, removed.
  Rejected with 400 if it equals `key` (self-parent) or if
  `_would_cycle()` is true.
- If the resulting entry is empty → the take is dropped from `takes`.

This is why editing from the parent side (`{key: childKey, parent_take: anchor}`)
does not disturb that child's `shot_name`.

### Where it is applied

`_apply_take_extras(rows, _load_take_extras())` runs immediately after
`_apply_shared_notes(...)` in every place rows are built:

- `/api/database` (line ~439)
- `/api/extract-slates-export` (line ~1283)
- the two global-export row builds in `api_extract_slates_export_all` /
  the PDF path (the `all_rows` sites, ~1981 / ~2055)

---

## 3. Offline / static HTML (`generate_html.py`)

`HTMLGenerator._apply_overlays()` step **4** mirrors the server: it loads
`__DATABASE/take_extras.json` and sets the same four `_`-fields (with a local
`_tk_label()` identical to `_take_label()`). Keep the two in sync when the label
format or field set changes.

---

## 4. Front-end (all inside the page's one big Python f-string)

### Card rendering

`renderDbDetails(row)` prepends `_extrasBoxHtml(row)` before the notes section:

```
_extrasBoxHtml(row)
  ├─ Shot Name row  — <input onchange="_saveShotName(this)">  (read-only span in OFFLINE_MODE)
  ├─ Parent Take row — badge → jumpToDbTake(); Change → openParentPicker(); × → _clearParentTake()
  └─ Children row    — one green badge per child (× → _detachChild()); "+ Add child…" → openChildPicker()
```

### Local model updates (no full reload)

| Function | Role |
|---|---|
| `_dbRowByKey(key)` | find a row in `dbRows` |
| `_takeLabelJs(row)` | JS twin of `_take_label()` |
| `_computeChildrenFor(parentKey)` | rebuild one parent's `_children_takes` from `dbRows` |
| `_descendants(key)` / `_ancestors(key)` | graph walks for picker exclusion |
| `_applyParentChange(childKey, newParentKey)` | update the child + **old parent + new parent** rows, then `_refreshExtrasUI()` each |
| `_refreshExtrasUI(key)` | re-render `.db-extras` (if expanded) + the title-line slots |
| `_saveTakeExtras(key, patch)` | `POST /api/take-extras/save` with `{key, ...patch}` |

Saves send only the changed sub-key(s) as `patch` — never the whole record.

### Title line

Pinned right, before the chevron, in `.db-title-right`:

- `_shotNamePillHtml(name)` — a `.db-shotname-pill.db-tag-clickable` that calls
  `setTagFilter('shot_name', name, event)` (same pattern as the slate/roll tags).
- `_titleRelSlotInner(row)` — `🔗` when the take has a parent (`title` = parent
  label), `⇊N` when it has N children.

### Parent / child picker (one modal, two modes)

Overlay `#linktake-picker-overlay` built by an IIFE. State: `_pickerKey`
(the take it was opened from) + `_pickerMode` (`'parent'` | `'child'`).

| Entry point | Mode | Picking take `T` does |
|---|---|---|
| `openParentPicker(key)` | `parent` | `save(key, {parent_take: T})` — set my parent |
| `openChildPicker(key)` | `child` | `save(T, {parent_take: key})` — adopt `T` as a child |

`_linkPickerRender()`:

- search field matches **Slate OR Roll only** (`fields = ['Slate', 'Roll']`,
  multi-term AND, cap 60 results)
- each option shows **Slate / T# / Roll** chips + VFX ID / scene sub-line; in
  child mode a candidate that already has a parent shows "currently child of …"
- excludes loop-forming choices: `_descendants(_pickerKey)` in parent mode,
  `_ancestors(_pickerKey)` in child mode, plus the anchor itself

`_doPickTake(targetKey)` performs the save + `_applyParentChange()` + closes.
Esc / click-outside → `closeLinkTakePicker()`.

### Navigation

`jumpToDbTake(targetKey)` — find `.entry[data-override-key="…"]`, expand it,
`scrollIntoView`, flash `.db-jump-flash`. Alerts if the target is filtered out /
omitted / not rendered.

---

## 5. Grouping, sorting, filtering

`DB_GROUP_MODES` (shared by `setDbGroup()` and `_restoreUiState()`) includes
`'shot_name'` and `'parent_take'`.

| Concern | Hook | `shot_name` | `parent_take` |
|---|---|---|---|
| Group | `dbGroupKey(row)` | `_shot_name` or `(no shot name)` | `_parent_take_label` or `(no parent take)` |
| Sort | `dbSortValue(row)` | lowercased `_shot_name`, empty → `￿` (last) | lowercased `_parent_take_label`, empty → `￿` |
| Filter field | `dbFilters.shot_name` / `.parent_take` in `dbRowMatches()` | substring of `_shot_name` | substring of `_parent_take_label` |

Group button ids `db-grp-shot_name` / `db-grp-parent_take`; sort `<option>`
values `shot_name` / `parent_take`; filter inputs `dbf-shot_name` /
`dbf-parent_take` (class `db-filter-input`, so the global "clear filters" paths
reset them automatically).

### "Only" toggles

Three independent checkboxes next to `EDITED ONLY`, AND-combined with everything
else (same behaviour as `SHOW OMITTED` / `EDITED ONLY`):

| Toggle | var | setter | checkbox id | keeps rows where |
|---|---|---|---|---|
| SHOT NAME ONLY | `showShotNameOnly` | `setShowShotNameOnly` | `show-shotname-cb` | `_shot_name` non-empty |
| PARENT ONLY | `showParentOnly` | `setShowParentOnly` | `show-parent-cb` | `_parent_take` non-empty |
| CHILDREN ONLY | `showChildrenOnly` | `setShowChildrenOnly` | `show-children-cb` | `_children_takes.length > 0` |

All three group modes, both sort keys, both filter fields and all three toggles
are persisted in `localStorage` (`vfx_ui_state`) via `_saveUiState()` /
`_restoreUiState()`.

---

## 6. Exports

Row data flows through every export path (§2), but as `_`-prefixed fields it is
**not yet surfaced as CSV / PDF / offline-HTML columns**. Adding those columns is
the remaining piece — treat it like `_note` / `_shared_note` (see the column
lists in `_openDbExportMenu`, the PDF `DB_SECTIONS`, and `_generate_db_csv`).

---

## 7. f-string / JS quoting rules

This all lives in one giant Python f-string. Same rules as elsewhere in the file:

- `{{` / `}}` → literal `{` / `}`; `${{x}}` → `${x}` (JS template literal)
- **Never** `\'` inside the f-string — use `&#39;` for a literal quote in an
  HTML attribute (e.g. `onclick="setTagFilter(&#39;shot_name&#39;,…)"`)
- **Never** a bare `\n`; a regex needs `\\s` (→ `\s` in the emitted JS)
- onclick handlers pass data via `data-*` + `this.dataset.*`, never by
  interpolating the value into the attribute string
