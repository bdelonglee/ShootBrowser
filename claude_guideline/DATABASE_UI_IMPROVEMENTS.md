# Database UI Improvements — Backlog

## 1. Sticky Group Headers
When the database is grouped (by scene, date, shoot day, etc.), the group header
should remain visible as the user scrolls through the takes inside that group.
- CSS `position: sticky; top: <toolbar-height>` on `.group-header`
- Need to account for the controls bar height (varies with filter row)

## 2. Take Tag on Folded Card
On the collapsed title line, add a Take badge immediately after the Slate tag.
- Same visual style as the existing `db-slate` / `db-roll` spans
- Shows the take number (e.g. "T3")

## 3. Click Tag to Set Filter
Clicking any of the following tags on the title line sets the corresponding
filter field automatically and re-renders the database:
| Tag element | Filter field |
|---|---|
| Slate | `slate` |
| Take | — (no filter field, skip or use global search) |
| VFX ID | `vfx_id` |
| Date | `date` |
| Shoot Day | `shoot_day` |
| Roll | `roll` |
| Lens | `lens` |
| Focal | `focal` |
- Visual feedback: brief highlight on the filter input that was set
- Must not conflict with the card expand/collapse toggle
- Use `event.stopPropagation()` to avoid triggering the card toggle

## 4. Copy Buttons (3 variants)

### 4a. Quick-copy button on folded card (right side, before chevron)
Copies a compact summary of the most important fields:
```
Slate: 10/1, VFX ID: J15__S10__APPA, Take: 2, Roll: A0043 C002
```
Fields: Slate, VFX ID, Take, Roll (omit empty fields).
- Small clipboard icon button, same style as bin-add-btn
- `navigator.clipboard.writeText()`
- Brief "Copied!" tooltip feedback

### 4b. Full-card copy button in expanded details (alongside Edit / Omit)
Copies all visible fields formatted with labels, one per line:
```
Slate:          10/1
VFX ID:         J15__S10__APPA
Scene:          Wide establishing shot
Take:           2
Roll:           A0043 C002
Lens:           Cooke S7 32mm
...
```
Uses the same field order as DB_SECTIONS.

### 4c. Click field value to copy (in expanded details)
Clicking any `db-field-value` span copies just that value to the clipboard.
- Cursor: `pointer` on hover
- Brief "Copied!" tooltip on the clicked element
- Does NOT interfere with the tag-filter feature (tags are on the title line,
  field values are in the expanded details)

## 5. Show Edited Only Filter
Mirror of "Show omitted" toggle — filters the database to only rows that
have at least one override (`row['_edited_fields'].length > 0`).
- Small toggle in the filter bar, same style as "SHOW / OMITTED"
- Label: "EDITED\nONLY"
- Persisted in `_saveUiState` / `_restoreUiState`
- Does NOT affect Queries page (overrides don't change counts meaningfully)

---

## Future — Assets Page
A new tab for 2D/3D/On-Set asset data, deliverable like Lidars.
Data structure TBD by user before implementation begins.
