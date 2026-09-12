# Added Takes — Creating & Duplicating Slate/Take Entries

Lets a user create a brand-new Slate/Take, or duplicate an existing take and
tweak it, from inside the Database view. **The source database JSON is never
modified** — an added take is a synthetic row injected into the pipeline
alongside the real ones.

This is a different kind of feature from Notes / Overrides / Take Extras
([`NOTES_AND_BINS.md`](NOTES_AND_BINS.md), [`TAKE_EXTRAS.md`](TAKE_EXTRAS.md)):
those all *annotate* a row that already exists in the source JSON. This one
*creates* rows that don't exist there at all. Read this doc before touching
any of it — the row-building pipeline has one extra step because of it, and
get that step wrong and added takes silently vanish or crash offline
generation (see the migration note in §1).

---

## 1. Storage

One JSON file **per take**, under:

```
{DATA_DIR}/__DATABASE/added_takes/<roll_slug>__<take_id>.json
```

- `take_id` is a fresh `uuid.uuid4()`, generated independently on whatever
  machine creates the take. So is `record_id` when the take starts a new
  slate. **This is the whole design**: because two machines can never
  generate the same uuid4, takes added on different machines can be merged
  by literally copying the files from one `added_takes/` folder into
  another — no merge tool, no conflict resolution, nothing else needed. If
  you ever touch this code, do not introduce anything that requires
  coordination between machines (sequence counters, "last id used" files,
  etc.) — that would break the entire point of the design.
- `<roll_slug>` is the take's `Roll` field, sanitized for filenames (spaces →
  `_`, characters illegal on Windows/macOS → `-`; see `_slugify_roll()`).
  It's purely for human readability when someone is looking at the folder —
  the app never parses it back out of the filename. If `Roll` is blank the
  file is just `<take_id>.json`. Because `take_id` is always present, the
  filename stays unique even if two takes share a Roll.
- Living in a **subdirectory** of `__DATABASE/` (not loose alongside the
  source database JSON exports) matters: `_db_jsonfiles()` — the function
  that finds "the newest database export" — globs `__DATABASE/*.json`
  **non-recursively**. A file in a subfolder is invisible to it automatically.
  This is deliberate, and it's the fix for a bug that bit `take_extras.json`
  earlier in the project's history: that file lives directly in
  `__DATABASE/`, so a *second*, separate exclusion list inside
  `HTMLGenerator` (`_DB_JSON_EXCLUDED`, a class attribute — distinct from the
  module-level one in `server.py`) had to be taught about it by hand, and
  initially wasn't — once `take_extras.json` became the newest `*.json` file,
  offline generation tried to parse it as a database export and crashed.
  Putting `added_takes/` in a subdirectory sidesteps that whole class of bug;
  don't move these files up a level without re-solving it.

### File format

```json
{
  "version": 1,
  "record_id": "2f5db220-2122-4070-a988-f24ca155f299",
  "take_id": "36f5d729-3c85-4d75-b573-c24050c5a0ce",
  "created_at": "2026-09-12T23:43:33",
  "duplicated_from": "00a23b91-...::051ab3d9-...",
  "fields": {
    "Slate": "5A/S", "Take": "3", "Roll": "D0013 C025", "...": "..."
  }
}
```

- `fields` holds the **flat, already-denormalized** field dict — the exact
  same shape `_denormalize_json_to_rows()` produces for a real take (see
  `DENORMALIZED_ROW_FIELDS` in generate_html.py — the single source of truth
  for "what fields exist" both for a blank take's defaults
  (`blank_added_take_fields()`) and for validating what `/api/added-takes/
  update` will accept). It is *not* the source JSON's nested
  `record`/`take`/`cameraSettings` shape — there's no reason to reimplement
  that nesting for synthetic data, and this way loading an added take never
  touches the denormalizer at all.
- `duplicated_from` is just provenance (which take, if any, this was copied
  from) — nothing reads it back except for display.

---

## 2. Server (`server.py`)

### Path / lookup helpers

| Function | Purpose |
|---|---|
| `_added_takes_dir()` | `{DATA_DIR}/__DATABASE/added_takes` |
| `_slugify_roll(roll)` | Roll → filesystem-safe fragment |
| `_added_take_write_path(roll, take_id)` | where a take **should** live, given its current Roll |
| `_find_added_take_file(take_id)` | locate a take's **actual** file by id, whatever its current Roll prefix (or lack of one — files created before the Roll-prefix change are still just `<take_id>.json`, and are found the same way) |
| `_load_added_take_rows()` | read every file into a row dict, shaped like a real row + `_is_added` |

`_load_added_take_rows()` skips filenames starting with `.` — on this
project's exFAT-formatted drive, macOS leaves `._<name>.json` AppleDouble
shadow files next to real ones, which would otherwise glob-match and fail to
parse as JSON (harmlessly, since both loaders already wrap the read in
`try/except`, but the dot-file skip avoids the wasted parse and any future
matching pattern like `_find_added_take_file`'s `*__{take_id}.json` glob,
which a shadow file could otherwise satisfy).

### Row fields added

`_load_added_take_rows()` stamps four fields onto each row, on top of the
flat `fields` dict:

| Row field | Source |
|---|---|
| `_record_id`, `_take_id` | from the file, same as any real row |
| `_is_added` | always `True` — this is the flag the front-end keys off |
| `_added_created_at` | `created_at` from the file |
| `_added_duplicated_from` | `duplicated_from` from the file |

Because `_record_id`/`_take_id` are already populated before
`_apply_overrides()` runs, added-take rows get a normal `_override_key`
(`f"{record_id}::{take_id}"`) for free — **Notes, Shared Notes, Shot Name,
Element Name, and Parent/Children links all work on added takes with zero
special-casing**, as long as the row-building order below is respected.

### Where rows get built — the one extra step

Every place that builds database rows now does:

```python
rows = _denormalize_json_to_rows(data) + _load_added_take_rows()
rows = _apply_overrides(rows, _load_overrides())
rows = _apply_omissions(rows, _load_omissions())        # /api/database only
rows = _apply_notes(rows, _load_notes())
rows = _apply_shared_notes(rows, _load_shared_notes())
rows = _apply_take_extras(rows, _load_take_extras())
```

The 4 call sites are `/api/database`, `/api/extract-slates-export`, and the
two `all_rows` sites in the global CSV/PDF export routes. **Adding a new
overlay pass, or a new row source like this one, means touching all 4 — and
the raw, no-overlays `/api/extract-slates` endpoint on purpose does *not* get
this treatment**, since its whole job is a faithful dump of the untouched
source JSON (matching why it never got `_apply_overrides`/notes/etc. either).
`HTMLGenerator._load_offline_db_rows()` (offline/static HTML) has the
equivalent `HTMLGenerator._load_added_take_rows()` method — keep the two
loader implementations in sync if the file format changes.

### Endpoints

**`POST /api/added-takes/create`** — body `{ mode: 'blank' | 'duplicate', source_key?, same_slate? }`

- `mode: 'blank'` → `fields = blank_added_take_fields()` (mostly empty;
  `Take` defaults to `'1'`, `Balls & Chart` / `VFX Pass / Ref` default to
  `'No'`, matching the source data's Yes/No convention), `record_id` is a
  fresh uuid4.
- `mode: 'duplicate'` → looks `source_key` up across **both** real rows and
  already-added rows (so you can duplicate an added take too), copies every
  non-`_`-prefixed field, and picks `record_id`:
  - `same_slate: true` → reuse the source take's `record_id` (new take, same
    slate)
  - `same_slate: false` → fresh uuid4 `record_id` (independent new slate)

  This choice is made by the user at duplicate time (a small modal — see
  §3), not decided by the backend.
- Either way, `Timestamp` is stamped to "now" (`%d/%m/%Y %H:%M:%S`, matching
  the source data's format) and `take_id` is a fresh uuid4. Returns
  `{ key: "<record_id>::<take_id>" }` so the front-end can jump straight to
  editing the new card.

**`POST /api/added-takes/update`** — body `{ key, fields: {...} }`

**Merges**, does not replace: `obj["fields"].update(...)`, filtered to keys
in `DENORMALIZED_ROW_FIELDS` (also acts as an allowlist against arbitrary
keys in the request body). This matters — an added take has no separate
"original" to diff against the way overrides do for real takes, so naively
overwriting the whole `fields` dict with whatever the edit panel currently
shows would silently wipe out any field the panel doesn't cover (`Timestamp`
is the one example today; there could be others later). Merge semantics mean
a partial-field save is always safe.

After merging, it recomputes `_added_take_write_path()` from the (possibly
just-changed) `Roll` and **renames the file if it no longer matches** — so a
take's filename self-heals to the current Roll on every edit, with no
separate migration step. (This is also how the two files that existed before
the Roll-prefix change were migrated — round-tripping them through this same
endpoint with their existing Roll value unchanged was enough to trigger the
rename.)

**`POST /api/added-takes/delete`** — body `{ key }` — finds the file via
`_find_added_take_file()` and unlinks it. Permanent; there is no undo and, on
purpose, no "Omit" alternative for added takes (see §3) — omission exists to
hide-without-modifying rows that come from a protected source; an added
take's file *is* the source, so deleting it is the natural, and only,
removal action.

---

## 3. Front-end (generate_html.py — all inside the page's one big Python f-string)

### Entry points

| UI | Function | Effect |
|---|---|---|
| "➕ New Take" button, Database toolbar | `createBlankTake()` | `create` with `mode:'blank'`, reloads, expands + opens the Edit panel on the new card |
| "⋮ Duplicate" button, every card's edit-actions row | `openDuplicateModal(key)` → `confirmDuplicate()` | small modal (same pattern as the existing Omit modal) asking same-slate vs. new-slate, then `create` with `mode:'duplicate'`, same reload+edit flow |
| "🗑 Delete" button (added takes only) | `deleteAddedTake(key)` | confirm() + `delete` + reload |

`_expandAndEdit(overrideKey)` is the shared "after create" step: find the
card by `data-override-key`, expand it if collapsed, scroll it into view,
then `openEditPanel()` after a short delay (the delay just gives the
just-rendered DOM a beat to settle before the panel looks it up).

### Card rendering

- `row['_is_added']` truthy adds `db-is-added` to the card's class list — an
  orange left border (`.db-is-added { border-left-color: #f0883e !important; }`),
  the same visual language as `.db-has-edits` (cyan) / `.vfx-pass` (green).
- Title line gets an `➕ added` badge (`.db-added-badge`, orange) — the
  "specific flag" that marks a card as not from the source database.
- The edit-actions row (`renderDbDetails`) computes `removalAction`: for an
  added take it's the Delete button; for a real take, the existing
  Omit/Restore logic is unchanged. `Revert` (which un-does `overrides.json`
  entries) is hidden entirely for added takes — they never write to
  `overrides.json`, so there's nothing to revert.

### Edit panel — extra fields for added takes only

`EDIT_SLATE_FIELDS` / `EDIT_TAKE_FIELDS` are the fields a **real** take's
override panel exposes. For a real take, fields like `Take` (number),
`Camera` (letter), `Camera Move`, `Resolution`, `Balls & Chart`,
`VFX Pass / Ref`, and `Date` are treated as identity fields tied to the
source database and aren't overridable. An added take has no such
constraint — there's no identity to protect — so `openEditPanel()` checks
`row['_is_added']` and, only then, appends two extra field lists:

```js
EDIT_SLATE_FIELDS_ADDED_EXTRA = [['Date', 'Date']]
EDIT_TAKE_FIELDS_ADDED_EXTRA  = [['Take', 'Take'], ['Camera Letter', 'Camera'],
    ['Camera Move', 'Camera Move'], ['Resolution', 'Resolution'],
    ['Balls & Chart', 'Balls & Chart'], ['VFX Pass / Ref', 'VFX Pass / Ref']]
```

The "Apply record-level changes to all takes of this slate" checkbox is also
hidden for added takes — that mechanism propagates edits into
`overrides.json` entries for *other, real* takes sharing the record_id, which
an added take has no business doing.

`saveEdit()` branches at the very top: `if (_editRow['_is_added']) return
_saveAddedTakeEdit();`. That function collects **every** field from the
combined (base + extra) field lists present in the panel and `POST`s the
whole set to `/api/added-takes/update` in one call — no edited-fields
diffing, no `_originals` tracking, because (as in §2) there's no baseline to
diff against; the merge semantics on the server side are what keep this safe
for fields the panel doesn't cover.

---

## 4. Things to know before extending this

- **Don't make added-take edits go through `/api/overrides/save`.** That
  endpoint computes `_edited_fields`/`_originals` by diffing against the
  *denormalized source row* — which doesn't exist for something that was
  never in the source JSON. Always route added-take field changes through
  `/api/added-takes/update`.
- **Any new per-take field/annotation you add to the app (a new sidecar file,
  a new overlay pass) works on added takes automatically** as long as it's
  keyed by `_override_key` the way Notes/Take Extras/etc. already are — no
  extra plumbing needed, *provided* `_load_added_take_rows()` is concatenated
  in before that overlay pass runs (§2). If you add a 5th row-building call
  site somewhere, remember the concatenation.
- **Group/Sort/Filter/"only" toggles have not been extended for added
  takes** (no "ADDED ONLY" toggle, no group-by-added mode). That's a
  deliberate scope cut, not an oversight — extend it the same way Shot
  Name's group/sort/filter/toggle set was added, if/when it's asked for.
- **CSV/PDF/offline-HTML exports already include added-take rows** (they
  flow through the same `_denormalize_json_to_rows(...) + _load_added_take_rows()`
  concatenation used everywhere else) but nothing marks them as added in
  those outputs — there's no "➕ added" equivalent in a CSV column or PDF
  page today.

---

## 5. f-string / JS quoting rules

Same rules as the rest of generate_html.py (see [`TAKE_EXTRAS.md`](TAKE_EXTRAS.md) §7):

- `{{` / `}}` → literal `{` / `}`; `${{x}}` → `${x}` (JS template literal)
- Never `\'` inside the f-string — use `&#39;` for a literal quote in an HTML
  attribute
- Never a bare `\n`
- onclick handlers pass data via `data-*` + `this.dataset.*`, not by
  interpolating a value straight into the attribute string
