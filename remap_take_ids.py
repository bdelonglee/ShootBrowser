#!/usr/bin/env python3
"""
remap_take_ids.py — Fix sidecar data orphaned by a source-database re-export.

The source system (whatever produces POSEIDON_*_db.json) regenerates every
record and take UUID on each re-export, even for takes that didn't change.
Every ShootBrowser sidecar file — Notes, Shared Notes, Overrides, Omissions,
Take Extras (Shot Name / Element Name / Parent-Child), and Added Takes'
record_id — is keyed by "{record_id}::{take_id}", so a fresh export silently
orphans all of it: nothing is deleted, it just no longer matches any row in
the new export, so the app shows none of it.

This tool re-links that data to the new export by matching on the one thing
that *does* stay stable across re-exports: (Slate, Take#, Camera, Timestamp).
See claude_guideline/ID_REMAP.md for the full story and why this is needed.

Dry-run is the DEFAULT — nothing changes unless you pass --apply (which then
still asks for interactive confirmation before writing).

Usage:
    python3 remap_take_ids.py <root>           # dry-run (safe)
    python3 remap_take_ids.py <root> --apply   # show report, confirm, then execute

<root> is the project root (contains DATA/__DATABASE/), matching server.py's
--root convention. Use --data to point at a DATA/ directory elsewhere.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

_DB_JSON_EXCLUDED = {
    "extraction_meta.json", "overrides.json", "omissions.json",
    "notes.json", "shared_notes.json", "take_extras.json",
}


# ── Loading ──────────────────────────────────────────────────────────────────

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def find_db_snapshots(db_dir: Path):
    """Every *_db.json export this project has, newest first — mirrors
    server.py's _load_db_json() selection (same dir, same exclusions, same
    dot-file skip), plus anything archived under _old/."""
    candidates = []
    for d in (db_dir, db_dir / "_old"):
        if not d.is_dir():
            continue
        for f in d.glob("*.json"):
            if f.name.startswith(".") or f.name in _DB_JSON_EXCLUDED:
                continue
            candidates.append(f)
    return sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True)


# ── Identity matching ────────────────────────────────────────────────────────

def index_db(db: dict):
    """override_key -> identity, identity -> override_key, identity -> count
    in this one export. Identity = (Slate, Take#, Camera, Timestamp) — the
    one tuple that survives a re-export unchanged."""
    rec_by_id = {r["id"]: r for r in db.get("records", [])}
    by_override, by_identity, counts = {}, {}, {}
    for t in db.get("takes", []):
        rec = rec_by_id.get(t.get("recordId", ""))
        if not rec:
            continue
        ident = (rec.get("slateId", ""), str(t.get("takeNumber", "")),
                 t.get("cameraLetter", ""), t.get("timestamp", ""))
        ok = rec["id"] + "::" + t["id"]
        by_override[ok] = ident
        by_identity[ident] = ok
        counts[ident] = counts.get(ident, 0) + 1
    return by_override, by_identity, counts


def build_remapper(old_dbs, new_db, added_take_ids):
    # Merge every old snapshot's index — a key might have been written
    # against any of several past exports. The old side can legitimately have
    # several override_keys pointing at one identity (one per snapshot the
    # take survived); that's not a conflict, they'd all land on the same new
    # key. Only ambiguity on the *new* side (two new takes, one identity)
    # means we can't safely pick a target.
    old_by_override = {}
    for old_db in old_dbs:
        ov, _, _ = index_db(old_db)
        old_by_override.update(ov)
    new_by_override, new_by_identity, new_counts = index_db(new_db)

    def make_log():
        return {"remapped": [], "already_current": [], "unresolved": [], "added_take_untouched": []}

    def remap_key(key, log):
        rid, tid = key.split("::", 1)
        if tid in added_take_ids:
            log["added_take_untouched"].append(key)
            return key, False
        if key in new_by_override:
            log["already_current"].append(key)
            return key, False
        ident = old_by_override.get(key)
        if ident is None:
            log["unresolved"].append((key, "not found in any old export on disk"))
            return key, False
        if new_counts.get(ident, 0) > 1:
            log["unresolved"].append((key, f"ambiguous identity {ident} in new export"))
            return key, False
        new_key = new_by_identity.get(ident)
        if new_key is None:
            log["unresolved"].append((key, f"identity {ident} not present in new export"))
            return key, False
        log["remapped"].append((key, new_key))
        return new_key, True

    def remap_record_id(record_id):
        """For added_takes' record_id (same-slate mode) — find the record's
        current id by slateId. A record_id absent from every old snapshot is
        a synthetic (new-slate mode) id that never came from a source export
        — leave it alone."""
        rec = None
        for old_db in old_dbs:
            rec = next((r for r in old_db.get("records", []) if r["id"] == record_id), None)
            if rec is not None:
                break
        if rec is None:
            return record_id, False
        slate_id = rec.get("slateId", "")
        new_rec = next((r for r in new_db.get("records", []) if r.get("slateId") == slate_id), None)
        if new_rec is None or new_rec["id"] == record_id:
            return record_id, False
        return new_rec["id"], True

    return remap_key, remap_record_id, make_log


# ── Per-file remap plans ─────────────────────────────────────────────────────

def plan_takes_dict(path: Path, remap_key_fn, log, remap_value_fields=()):
    """For sidecar files shaped {"version":1,"takes":{override_key: {...}}} —
    Take Extras, Notes, Shared Notes. remap_value_fields lists entry fields
    that themselves hold an override_key needing the same treatment
    (Take Extras' "parent_take")."""
    if not path.exists():
        return None, []
    data = load(path)
    new_takes, collisions = {}, []
    for key, entry in data.get("takes", {}).items():
        new_key, _ = remap_key_fn(key, log)
        if isinstance(entry, dict):
            entry = dict(entry)
            for f in remap_value_fields:
                if entry.get(f):
                    entry[f], _ = remap_key_fn(entry[f], log)
        if new_key in new_takes:
            collisions.append((key, new_key, new_takes[new_key], entry))
            if isinstance(entry, dict) and isinstance(new_takes[new_key], dict):
                merged = dict(new_takes[new_key]); merged.update(entry)
                new_takes[new_key] = merged
            # else: keep the first (string notes) — identical content in practice
        else:
            new_takes[new_key] = entry
    data["takes"] = new_takes
    return data, collisions


def plan_overrides(path: Path, remap_key_fn, log):
    if not path.exists():
        return None, []
    data = load(path)
    new_overrides, collisions = {}, []
    for key, entry in data.get("overrides", {}).items():
        new_key, _ = remap_key_fn(key, log)
        if new_key in new_overrides:
            collisions.append((key, new_key, new_overrides[new_key], entry))
        new_overrides[new_key] = entry
    data["overrides"] = new_overrides
    return data, collisions


def plan_omissions(path: Path, remap_key_fn, remap_record_id_fn, log):
    if not path.exists():
        return None
    data = load(path)
    data["takes"] = list(dict.fromkeys(
        remap_key_fn(k, log)[0] for k in data.get("takes", [])
    ))
    data["slates"] = list(dict.fromkeys(
        remap_record_id_fn(r)[0] for r in data.get("slates", [])
    ))
    return data


def plan_added_takes(added_files, remap_key_fn, remap_record_id_fn, log):
    updates = []
    for f in added_files:
        obj = load(f)
        new_rid, changed = remap_record_id_fn(obj.get("record_id", ""))
        new_dup = obj.get("duplicated_from", "")
        dup_changed = False
        if new_dup:
            new_dup, dup_changed = remap_key_fn(new_dup, log)
        if changed or dup_changed:
            new_obj = dict(obj)
            new_obj["record_id"] = new_rid
            if new_dup:
                new_obj["duplicated_from"] = new_dup
            updates.append((f, obj, new_obj))
    return updates


# ── Main ──────────────────────────────────────────────────────────────────────

def report_log(name: str, log: dict) -> None:
    print(f"{name}: {len(log['remapped'])} remapped, "
          f"{len(log['already_current'])} already current, "
          f"{len(log['added_take_untouched'])} added-take (untouched), "
          f"{len(log['unresolved'])} unresolved")
    for k, reason in log["unresolved"]:
        print(f"  UNRESOLVED: {k} - {reason}")


def report_collisions(name: str, collisions: list) -> None:
    if not collisions:
        return
    print(f"\n{len(collisions)} collision(s) in {name} (two old keys -> same new key):")
    for old_key, new_key, existing, incoming in collisions:
        same = "identical content" if existing == incoming else "DIFFERENT CONTENT — merged, please review"
        print(f"  -> {new_key}  ({same})")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Re-link ShootBrowser sidecar data after the source database is re-exported.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("root", help="Project root (contains DATA/__DATABASE/)")
    ap.add_argument("--data", default=None, help="Override the DATA/ directory path")
    ap.add_argument("--apply", action="store_true",
                     help="Execute changes after confirmation (default: dry-run only)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    data_dir = Path(args.data).resolve() if args.data else root / "DATA"
    db_dir = data_dir / "__DATABASE"
    if not db_dir.is_dir():
        sys.exit(f"ERROR: {db_dir} does not exist.")

    snapshots = find_db_snapshots(db_dir)
    if len(snapshots) < 2:
        sys.exit(f"Found {len(snapshots)} database export(s) in {db_dir} (and _old/) — "
                  "need at least 2 (one to remap from, one current) to do anything.")
    new_path, old_paths = snapshots[0], snapshots[1:]

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] Current export : {new_path.name}")
    print(f"[{mode}] Matching against: {', '.join(p.name for p in old_paths)}\n")

    new_db = load(new_path)
    old_dbs = [load(p) for p in old_paths]

    added_dir = db_dir / "added_takes"
    added_files = sorted(f for f in added_dir.glob("*.json") if not f.name.startswith("."))
    added_take_ids = {load(f).get("take_id", "") for f in added_files}

    remap_key_fn, remap_record_id_fn, make_log = build_remapper(old_dbs, new_db, added_take_ids)

    te_log = make_log()
    te_data, te_collisions = plan_takes_dict(
        db_dir / "take_extras.json", remap_key_fn, te_log, remap_value_fields=("parent_take",)
    )

    notes_log = make_log()
    notes_data, notes_collisions = plan_takes_dict(db_dir / "notes.json", remap_key_fn, notes_log)

    shared_log = make_log()
    shared_data, shared_collisions = plan_takes_dict(db_dir / "shared_notes.json", remap_key_fn, shared_log)

    ov_log = make_log()
    ov_data, ov_collisions = plan_overrides(db_dir / "overrides.json", remap_key_fn, ov_log)

    om_log = make_log()
    om_data = plan_omissions(db_dir / "omissions.json", remap_key_fn, remap_record_id_fn, om_log)

    added_updates = plan_added_takes(added_files, remap_key_fn, remap_record_id_fn, make_log())

    if te_data is not None:
        report_log("take_extras.json", te_log)
        report_collisions("take_extras.json", te_collisions)
    if notes_data is not None:
        report_log("notes.json", notes_log)
        report_collisions("notes.json", notes_collisions)
    if shared_data is not None:
        report_log("shared_notes.json", shared_log)
        report_collisions("shared_notes.json", shared_collisions)
    if ov_data is not None:
        report_log("overrides.json", ov_log)
        report_collisions("overrides.json", ov_collisions)
    if om_data is not None:
        report_log("omissions.json", om_log)
    if added_updates:
        print(f"added_takes/: {len(added_updates)} record_id update(s)")
        for f, old_obj, new_obj in added_updates:
            print(f"  {f.name}: record_id {old_obj['record_id']} -> {new_obj['record_id']}")

    if not args.apply:
        print("\n[DRY RUN] Nothing was changed. Re-run with --apply to execute.")
        return

    ans = input(f"\nApply these changes in {db_dir}? [y/N] ").strip().lower()
    if ans != "y":
        print("Aborted.")
        return

    backup_dir = db_dir / "_id_remap_backup"
    backup_dir.mkdir(exist_ok=True)

    def write(path: Path, data):
        if data is None:
            return
        if path.exists():
            shutil.copy2(path, backup_dir / (path.name + ".bak"))
        save(path, data)

    write(db_dir / "take_extras.json", te_data)
    write(db_dir / "notes.json", notes_data)
    write(db_dir / "shared_notes.json", shared_data)
    write(db_dir / "overrides.json", ov_data)
    write(db_dir / "omissions.json", om_data)
    for f, old_obj, new_obj in added_updates:
        shutil.copy2(f, backup_dir / (f.name + ".bak"))
        save(f, new_obj)

    print(f"\nDone. Backups in {backup_dir}")


if __name__ == "__main__":
    main()
