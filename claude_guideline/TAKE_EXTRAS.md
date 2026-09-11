# Take Extras — Shot Names & Parent / Children Takes

User-authored per-take fields shown at the top of every expanded Database card:

| Field | Type | Stored | Derived |
|---|---|---|---|
| **Shot Name(s)** | any number of free strings | yes (`shot_names`) | — |
| **Parent Take** | one take key | yes (`parent_take`) | `_parent_take_label` |
| **Children Takes** | many take keys | no | reverse lookup of `parent_take` |

A take can carry **any number of Shot Names** (badges, added/removed one at a
time — same UI pattern as Children). It has **at most one parent** and **any
number of children**. The parent link is edited from either side (set my parent
from the child card, or add a child from the parent card) — both write the same
single field: `parent_take` on the child.

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
      "shot_names": ["SH_010_020", "SH_010_021"],
      "parent_take": "<record_id>::<take_id>"
    }
  }
}
```

- **Key** = `_override_key` = `f"{_record_id}::{_take_id}"`, stamped onto every
  row by `_apply_overrides()` — which **must run before** `_apply_take_extras()`
  (server.py) / step 4 of `HTMLGenerator._apply_overlays()` (generate_html.py).
- An entry only holds the sub-keys that are set. When all of them are cleared
  the whole entry is deleted (never left as `{}`).
- `take_extras.json` is excluded from being read as a source database export in
  **two separate places** — keep both in sync if you rename the file or add
  another sidecar:
  - `_DB_JSON_EXCLUDED` (module-level set, server.py) — used by `/api/database`
    and the export routes.
  - `HTMLGenerator._DB_JSON_EXCLUDED` (class attribute, generate_html.py) — used
    by `_db_jsonfiles()` to pick the newest database export for offline/static
    generation. **This one was missed when the feature first shipped**: once
    `take_extras.json` became the newest `*.json` in `__DATABASE/`, offline
    generation picked it up as if it were a database export and crashed
    (`_denormalize_json_to_rows` iterating its `"takes"` *dict* as if it were the
    source JSON's `"takes"` *list* — same key name, different shape). Fixed by
    adding it there too; watch for this pattern with any future sidecar file.
- **Legacy fields**, both still read on load and rewritten to the current shape
  on next save:
  - `parent_take` was originally `linked_take` — `_extras_parent()` falls back.
  - `shot_names` was originally the singular `shot_name`. Some existing entries
    held **several names jammed into one string, space-separated** (e.g.
    `"040_00200_POAN    040_00400_POAN   040_01400_POAN"`) from before
    multi-name support existed. `_extras_shot_names()` /
    `_tk_shot_names()` fall back to `ext.get("shot_name").split()` (splits on
    any whitespace, collapses repeats) — so those migrate into separate badges
    automatically, with no data rewritten until the take is next edited.

---

## 2. Server (`server.py`)

### Helpers

| Function | Purpose |
|---|---|
| `_take_extras_path()` | `{DATA_DIR}/__DATABASE/take_extras.json` |
| `_load_take_extras()` | → `{"version": 1, "takes": {}}` on any error |
| `_save_take_extras(x)` | pretty JSON, `ensure_ascii=False` |
| `_extras_parent(ext)` | parent key from an entry, accepts legacy `linked_take` |
| `_extras_shot_names(ext)` | shot-name list from an entry — accepts legacy singular `shot_name`, splitting it on whitespace; trims, drops empties, dedupes, preserves order |
| `_take_label(row)` | `"Slate <slate>/T<take> · Roll <roll>"` — badge / picker text |
| `_apply_take_extras(rows, extras)` | annotate rows (below) |
| `_would_cycle(takes, child, new_parent)` | walk the parent chain, detect loops |

### `_apply_take_extras(rows, extras)` — row annotations

Runs one pass to read `shot_names` / `parent_take` and build a
`parent → [child keys]` index, then a second pass to resolve labels:

| Row field | Value |
|---|---|
| `_shot_names` | `[str, …]` (`[]` if none) — via `_extras_shot_names()` |
| `_parent_take` | parent's `_override_key` (`''` if none) |
| `_parent_take_label` | `_take_label()` of the parent row, or `''` |
| `_children_takes` | `[{ "key": <override_key>, "label": <take_label> }, …]`, sorted by label |

All fields are `_`-prefixed, so they never leak into CSV `default_cols`
(`[f for f in row if not f.startswith("_")]`).

### Endpoint — `POST /api/take-extras/save`

Body: `{ "key": <override_key>, "shot_names"?: string[], "parent_take"?: str }`

**Merge semantics** — only the sub-keys *present in the body* are touched:

- `shot_names` present → **full-array replace** (trimmed, deduped, empties
  dropped); an empty array removes the field. There is no per-name add/remove
  endpoint — the client always sends the whole next array (see §4).
- `parent_take` (or `linked_take`) present → set or, if empty, removed.
  Rejected with 400 if it equals `key` (self-parent) or if
  `_would_cycle()` is true.
- If the resulting entry is empty → the take is dropped from `takes`.

This is why editing from the parent side (`{key: childKey, parent_take: anchor}`)
does not disturb that child's `shot_names`, and why adding one shot name doesn't
disturb `parent_take`.

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
`__DATABASE/take_extras.json` and sets the same four `_`-fields, with local
twins `_tk_label()` (≡ `_take_label()`) and `_tk_shot_names()`
(≡ `_extras_shot_names()`, same whitespace-split legacy fallback). Keep all
three pairs in sync when the label format or field set changes.

---

## 4. Front-end (all inside the page's one big Python f-string)

### Card rendering

`renderDbDetails(row)` prepends `_extrasBoxHtml(row)` before the notes section:

```
_extrasBoxHtml(row)
  ├─ Shot Name row   — one blue badge per name (× → _removeShotName()); a free-text
  │                    "+ add shot name…" input (blur/Enter → _addShotName())
  ├─ Parent Take row — badge → jumpToDbTake(); Change → openParentPicker(); × → _clearParentTake()
  └─ Children row    — one green badge per child (× → _detachChild()); "+ Add child…" → openChildPicker()
```

Shot Name and Children are now the same pattern — badges + one "add" affordance
— except Shot Name is free text typed inline, while Children is picked from a
modal (you're choosing an existing take, not typing a name).

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
| `_addShotName(inp)` | read + trim the "add" input, append to `row['_shot_names']` if not already present, save the **whole new array**, clear the input synchronously before the `await` (guards against a stray `blur` firing twice after `Enter`) |
| `_removeShotName(key, name)` | filter `name` out of `row['_shot_names']`, save the whole new array |

Saves send only the changed sub-key(s) as `patch`; for `shot_names` that "changed
sub-key" is always the **full next array**, never a single add/remove op —
matching the merge semantics in §2 (see there for why per-name endpoints would
be unnecessary complexity).

### Title line

Pinned right, before the chevron, in `.db-title-right`:

- `_shotNamePillsHtml(names)` — one `.db-shotname-pill.db-tag-clickable` per
  name, each calling `setTagFilter('shot_name', name, event)` (same pattern as
  the slate/roll tags).
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
| Group | `dbGroupKey(row)` | `_shot_names.join(', ')` or `(no shot name)` — **one group per exact name-set**, not one group per name | `_parent_take_label` or `(no parent take)` |
| Sort | `dbSortValue(row)` | `_shot_names` sorted + joined + lowercased, empty → `￿` (last) | lowercased `_parent_take_label`, empty → `￿` |
| Filter field | `dbFilters.shot_name` / `.parent_take` in `dbRowMatches()` | substring match against **any** name in `_shot_names` (`.some(...)`) | substring of `_parent_take_label` |

Group button ids `db-grp-shot_name` / `db-grp-parent_take`; sort `<option>`
values `shot_name` / `parent_take`; filter inputs `dbf-shot_name` /
`dbf-parent_take` (class `db-filter-input`, so the global "clear filters" paths
reset them automatically).

**Known limitation:** grouping by Shot Name buckets each take under its whole
name-set (`"A, B"` is a different group from `"A"` or `"B"`), it does not fan a
multi-name take out into each of its groups. Fine for the common case (0 or 1
name); revisit if multi-name takes become common enough that this reads wrong.

### "Only" toggles

Three independent checkboxes next to `EDITED ONLY`, AND-combined with everything
else (same behaviour as `SHOW OMITTED` / `EDITED ONLY`):

| Toggle | var | setter | checkbox id | keeps rows where |
|---|---|---|---|---|
| SHOT NAME ONLY | `showShotNameOnly` | `setShowShotNameOnly` | `show-shotname-cb` | `_shot_names.length > 0` |
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
