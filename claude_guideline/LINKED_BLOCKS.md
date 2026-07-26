# Linked Browse Blocks — Feature Reference

Expanded take cards in the Database view show a **LINKED BLOCKS** section that
cross-references the take's VFX ID against Browse entries and displays matching
blocks as clickable badges.

---

## 1. Data sources

### VFX ID (take side)
Each database row may have a `customData.VFX ID` field. After denormalization
(`_denormalize_json_to_rows` in `generate_html.py`) it ends up as a flat string
field `"VFX ID"` on the row object, e.g. `"J23__S05__RITZ"`.

The format mirrors Browse block directory names: `{day}__{scenes}__{codes}`
— double-underscore separators, single-underscore between multiple scenes or codes.

### Browse entries (block side)
All Browse entries are pre-indexed into the JS global `allEntries` (a flat
`path → entry` object built at startup from `data.by_days`). Each entry has:

```js
{
  path:        "/abs/path/to/block",
  day:         "J23",
  scenes:      ["S05", "S12"],   // array of scene strings
  code:        "RITZ_METR",      // underscore-joined codes string
  description: "Chambre Ritz",
  ...
}
```

---

## 2. Matching logic (isolated functions)

### `parseVfxId(vfxId) → {day, scenes[], codes[]} | null`

Pure parser — no side effects, no DOM access. Splits the VFX ID string into its
three components. Returns `null` for anything that doesn't match the expected
3-part `__`-separated pattern (missing field, empty segments, wrong type).

```js
parseVfxId("J23__S05__RITZ")
// → { day: "J23", scenes: ["S05"], codes: ["RITZ"] }

parseVfxId("J23__S05_S12__RITZ_METR")
// → { day: "J23", scenes: ["S05","S12"], codes: ["RITZ","METR"] }

parseVfxId("bad string")  // → null
parseVfxId(null)          // → null
```

### `matchBrowseBlocks(parsed) → {direct[], potential[]}`

Iterates `Object.values(allEntries)` and classifies entries. Both arrays contain
full entry objects (same shape as Browse entries).

**Matching rules (current):**

| Condition | Classification |
|---|---|
| day mismatch | skipped entirely |
| day match + scene overlap + code overlap | `direct` |
| day match + scene overlap only | `potential` |
| day match + code overlap only | `potential` |
| day match + no overlap | skipped |

"Overlap" means at least one element in common (set intersection ≠ ∅).
The block may have *more* scenes/codes than the VFX ID — it just needs to
*include* the VFX ID's values.

**To change the matching rules**, edit only `matchBrowseBlocks`. `parseVfxId`
and the rendering layer are unaffected.

---

## 3. Rendering pipeline

```
renderDbDetails(row)
  └── renderLinkedBlocks(row['VFX ID'])
        ├── parseVfxId(vfxId)          → parsed components
        ├── matchBrowseBlocks(parsed)   → { direct[], potential[] }
        └── HTML: .db-linked-blocks
              ├── .db-linked-row  (direct badges, green)
              └── .db-linked-row  (potential badges, amber)
```

`renderLinkedBlocks` returns `''` if there are no matches, so no section is
rendered for takes without a VFX ID or with no matching blocks.

The section is injected between the field sections and the edit action buttons:
```js
return `<div class="db-details">
    ${notesSection}${photoStrip}${sections}${linkedBlocks}${editActions}
</div>`;
```

---

## 4. Navigation

### `jumpToBrowseEntry(path)`

Called by the badge `onclick`. Sequence:

1. `history.replaceState({_jumpNav:true, view:'database', scrollTop: window.scrollY}, '')`
   — stamps the current history entry with database scroll position.
2. `history.pushState({_jumpNav:true, view:'browse', entryPath: path}, '')`
   — adds a Browse entry to the browser history stack.
3. `setView('browse')` — switches the visible view.
4. `requestAnimationFrame(...)` — finds the target entry in the DOM by iterating
   `#view-browse .entry[data-path]` (attribute selector + loop, avoids CSS
   escaping issues with path strings), expands it, scrolls it into view.

### `popstate` listener (end of script)

```js
window.addEventListener('popstate', e => {
    const state = e.state;
    if (!state || !state._jumpNav) return;   // ignore non-jump history events
    if (state.view === 'database') {
        setView('database');
        if (state.scrollTop != null) {
            requestAnimationFrame(() => window.scrollTo(0, state.scrollTop));
        }
    }
});
```

The `_jumpNav` marker prevents this handler from reacting to any other
`pushState` calls that may be added in the future.

---

## 5. CSS class reference

| Class | Element | Style |
|---|---|---|
| `.db-linked-blocks` | Section wrapper | flex column, gap 6px |
| `.db-linked-row` | One tier of badges (direct or potential) | flex wrap, gap 5px |
| `.db-linked-badge` | Base badge style | pill, 0.8em, `filter` transition on hover |
| `.db-linked-direct` | Direct link badge | green — `#56d364`, rgba(86,211,100) bg+border |
| `.db-linked-potential` | Potential link badge | amber — `#e3b341`, rgba(227,179,65) bg+border |

Section header reuses `.db-section-label` (accent color, small caps, border-bottom).

---

## 6. Important implementation notes

### f-string / JS quoting rules
All JS lives inside a Python f-string. Rules:
- `{{` / `}}` → literal `{` / `}` in JS output
- `${{var}}` → `${var}` (JS template literal interpolation)
- Never use `\'` inside the f-string — use `&#39;` for literal single quotes in HTML attributes
- Never use bare `\n` inside the f-string for JS strings

### `allEntries` availability
`allEntries` is built at script startup from `data.by_days`. It is always
populated before any user interaction, so `matchBrowseBlocks` can safely read it
at render time. Do not call `matchBrowseBlocks` during module initialisation
(before the `for` loop that populates it).

### Badge onclick — `data-path` pattern
Badge onclick handlers store the path in `data-path` and read it back via
`this.dataset.path` — the same pattern used throughout the codebase to avoid
HTML attribute single-quote escaping issues.

---

## 7. Extension points

- **Relax day constraint for potential links**: remove `if (entry.day !== parsed.day) continue;`
  from `matchBrowseBlocks` and add day-mismatch as a third tier.
- **Third tier (day-only match)**: add a `dayOnly[]` array for blocks that share
  only the day, and render a third row with a distinct colour.
- **Tooltip enrichment**: replace `title="Direct link"` with a richer string
  showing which scenes/codes matched (available from `parsed` and `entry`).
- **Multiple VFX IDs per take**: if a take can have several VFX IDs (comma- or
  semicolon-separated), split the field in `renderLinkedBlocks` before calling
  `parseVfxId`, deduplicate results, and merge tiers.
