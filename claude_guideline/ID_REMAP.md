# ID Remap — Sidecar Data Orphaned by a Source-Database Re-Export

**The source system regenerates every `record_id` and `take_id` on every
re-export**, even for takes that didn't change. Every ShootBrowser sidecar
file — Notes, Shared Notes, Overrides, Omissions, Take Extras (Shot Name /
Element Name / Parent-Child — see [`TAKE_EXTRAS.md`](TAKE_EXTRAS.md)), and
Added Takes' `record_id` (see [`ADDED_TAKES.md`](ADDED_TAKES.md)) — is keyed
by `"{record_id}::{take_id}"` (`_override_key`). So the moment the user
updates `DATA/__DATABASE/` with a freshly-exported `POSEIDON_*_db.json`,
**every one of those sidecar entries silently orphans**: nothing is deleted,
it just no longer matches any row in the new export, so the app shows none
of it. From the user's side this looks exactly like "I lost all my Shot
Names" (or Notes, or anything else) — first reported and diagnosed
2026-09-14.

**Fix: [`remap_take_ids.py`](../remap_take_ids.py)** — run it (from the
project root, or point it at the STRUCTURE root) whenever a fresh database
export goes into `DATA/__DATABASE/`:

```bash
python3 remap_take_ids.py "/Volumes/Crucial X10/POSEIDON/STRUCTURE"           # dry-run (safe)
python3 remap_take_ids.py "/Volumes/Crucial X10/POSEIDON/STRUCTURE" --apply   # asks to confirm, then writes
```

No other arguments needed — it auto-discovers every `*_db.json` export in
`__DATABASE/` **and** `__DATABASE/_old/`, picks the newest by mtime as
"current" (the exact same selection `_load_db_json()` / `_db_jsonfiles()`
use), and treats every other one as a candidate to match sidecar keys
against.

---

## 1. Why matching works at all

Two exports of "the same" take get **different UUIDs** but keep the
**same** `(Slate, Take#, Camera, Timestamp)`. Verified directly on this
project's data (2026-09-14): a take with `Slate "40/16"`, `Take 3`,
`Camera F`, `Timestamp 2026-05-28T12:41:13.599Z` existed in the `07-03`
export as one record/take UUID pair and in the `07-16` export as a
**completely different** pair — same identity, zero UUID overlap. That
4-tuple is `remap_take_ids.py`'s entire strategy: for every sidecar
`override_key` that no longer matches the current export, look up its
identity in *any* older export that still has that key, then find the
current export's override_key with the same identity.

**Timestamp matters as much as Slate/Take/Camera** — without it, two
takes sharing a slate/take/camera (a re-slate, or camera letter reuse
across days) would collide. Even with all four, a small number of
genuine duplicates exist in real data (24 out of ~4477 takes in this
project) — `remap_take_ids.py` reports those as `unresolved` rather than
guessing.

## 2. What gets remapped, and how

| File | Shape | What's remapped |
|---|---|---|
| `take_extras.json` | `{"takes": {override_key: {...}}}` | every top-level key; the `parent_take` value inside each entry too |
| `notes.json`, `shared_notes.json` | `{"takes": {override_key: text}}` | every top-level key |
| `overrides.json` | `{"overrides": {override_key: {...}}}` | every top-level key |
| `omissions.json` | `{"takes": [override_key, ...], "slates": [record_id, ...]}` | every list element (takes via key remap, slates via record-id remap) |
| `added_takes/*.json` | one file per take, `record_id` field | `record_id`, **only** if it's found in an old export at all — a "new slate" added take's `record_id` is a fresh `uuid4()` that never came from any export, and must never be touched |

A key already valid against the current export is left alone
(`already_current`). A key belonging to an Added Take (its `take_id` is a
synthetic id, never in any source export) is never touched
(`added_take_untouched`) — matched by checking the id against every
`added_takes/*.json`'s own `take_id` up front.

**Ambiguity is checked only on the new-export side** — if two different old
override_keys resolve to the same identity (because the same real take
appears, correctly, in more than one archived export), that's expected and
not a conflict; both remap to the same current key, and
`plan_takes_dict()`'s collision handling merges them (logged, and flagged if
their content actually differs — it didn't, ever, in the one real collision
seen so far). What *would* block a remap is the **current** export having
two different takes share one identity — that's logged as `unresolved` and
left alone rather than guessed at.

## 3. Recovering this project's real data (2026-09-14)

`take_extras.json` (38 entries) was written against a mix of the `07-03`
export (the freshest 30) and, for 2 entries, already against `07-16`
directly (added after the DB had been updated) — matched cleanly on the
first attempt using `07-03` alone as the "old" source, 0 unresolved.

`notes.json` (84 entries) turned out to have been written almost entirely
against the **`06-22`** export — 82/84 needed `06-22`, not `07-03`; only 2
needed `07-03`. This is exactly why the tool merges **every** available old
export rather than taking a single `--old` path: a sidecar file's keys can
predate the most recent prior export by more than one generation, and
there's no way to know in advance which snapshot(s) a given key was written
against.

Both `added_takes/*.json` entries turned out to be "same slate" mode (their
`record_id` came from a real, now-stale, source record) and got remapped
too — confirmed against the new export's `slateId` before and after.

All of this was verified with real dry-run counts (`0 unresolved` on both
files) before writing anything, and confirmed against a live `/api/database`
call afterward (35 takes correctly showing Shot Name / Element Name again).

## 4. If you're extending this

- **Any new sidecar file keyed by `_override_key`** needs a `plan_*()`
  function here mirroring whichever of `plan_takes_dict()` (dict of
  override_key → value) or `plan_omissions()`-style (list of override_keys)
  matches its shape — don't forget it, or the next re-export will silently
  orphan that data too, exactly like this one did for Take Extras.
- **This is a symptom worth recognizing on sight**: if a user reports that
  per-take data they entered "disappeared" after they updated the source
  database, check `ls -la DATA/__DATABASE/*_db.json` for a newer mtime than
  the sidecar files first — don't assume data loss until you've ruled out
  orphaning.
- A real, standing fix beyond "remember to run this script" would be
  wiring a version of this remap into the app itself — e.g., detect on
  startup that the active `*_db.json` changed since the sidecar files were
  last touched, and offer to run the remap before loading. Not built yet;
  flagged here so it isn't lost.
