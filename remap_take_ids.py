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

This module re-links that data to the new export by matching on the one
thing that *does* stay stable across re-exports: (Slate, Take#, Camera,
Timestamp). See claude_guideline/ID_REMAP.md for the full story.

This file is a standalone module on purpose — server.py only ever calls
find_orphans() (cheap: current export only) and run_remap() (the full fix)
and never reimplements the matching logic itself. See "Library API" below
if you're wiring this into something else.

CLI usage (dry-run is the DEFAULT — nothing changes unless you pass --apply,
which then still asks for interactive confirmation before writing):

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

_SIDECAR_FILES = ("take_extras.json", "notes.json", "shared_notes.json", "overrides.json")


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


def _added_take_ids(db_dir: Path) -> set:
    added_dir = db_dir / "added_takes"
    if not added_dir.is_dir():
        return set()
    ids = set()
    for f in added_dir.glob("*.json"):
        if f.name.startswith("."):
            continue
        try:
            ids.add(load(f).get("take_id", ""))
        except Exception:
            pass
    return ids


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


# ── Cheap status check — current export only, no old snapshots loaded ───────

def find_orphans(db_dir: Path, new_db: dict) -> dict:
    """How many keys in each sidecar file don't match the current export?
    Only needs the already-loaded current export (the caller almost always
    has this cached already) — never touches old snapshots, so this is safe
    to call on every server startup or Database-tab load. Returns
    {sidecar_filename: orphaned_key_count}; a file absent or fully clean is
    omitted, so an empty dict means nothing needs fixing."""
    new_by_override, _, _ = index_db(new_db)
    added_ids = _added_take_ids(db_dir)
    result = {}

    def count_orphans(keys):
        return sum(1 for k in keys
                   if k.split("::", 1)[-1] not in added_ids and k not in new_by_override)

    for name in ("take_extras.json", "notes.json", "shared_notes.json"):
        p = db_dir / name
        if not p.exists():
            continue
        try:
            n = count_orphans(load(p).get("takes", {}).keys())
        except Exception:
            continue
        if n:
            result[name] = n

    p = db_dir / "overrides.json"
    if p.exists():
        try:
            n = count_orphans(load(p).get("overrides", {}).keys())
            if n:
                result["overrides.json"] = n
        except Exception:
            pass

    p = db_dir / "omissions.json"
    if p.exists():
        try:
            n = count_orphans(load(p).get("takes", []))
            if n:
                result["omissions.json"] = n
        except Exception:
            pass

    return result


# ── Remap plan ───────────────────────────────────────────────────────────────

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


def plan_all(db_dir: Path, new_db: dict, old_dbs: list) -> dict:
    """Build the full remap plan for every sidecar file. Returns a dict with
    one entry per file (data + log + collisions) plus 'added_updates' —
    nothing is written to disk yet. Shared by the CLI and run_remap()."""
    added_dir = db_dir / "added_takes"
    added_files = sorted(f for f in added_dir.glob("*.json") if not f.name.startswith(".")) \
        if added_dir.is_dir() else []
    added_take_ids = {load(f).get("take_id", "") for f in added_files}

    remap_key_fn, remap_record_id_fn, make_log = build_remapper(old_dbs, new_db, added_take_ids)

    plan = {}

    log = make_log()
    data, collisions = plan_takes_dict(
        db_dir / "take_extras.json", remap_key_fn, log, remap_value_fields=("parent_take",)
    )
    plan["take_extras.json"] = {"path": db_dir / "take_extras.json", "data": data, "log": log, "collisions": collisions}

    log = make_log()
    data, collisions = plan_takes_dict(db_dir / "notes.json", remap_key_fn, log)
    plan["notes.json"] = {"path": db_dir / "notes.json", "data": data, "log": log, "collisions": collisions}

    log = make_log()
    data, collisions = plan_takes_dict(db_dir / "shared_notes.json", remap_key_fn, log)
    plan["shared_notes.json"] = {"path": db_dir / "shared_notes.json", "data": data, "log": log, "collisions": collisions}

    log = make_log()
    data, collisions = plan_overrides(db_dir / "overrides.json", remap_key_fn, log)
    plan["overrides.json"] = {"path": db_dir / "overrides.json", "data": data, "log": log, "collisions": collisions}

    log = make_log()
    data = plan_omissions(db_dir / "omissions.json", remap_key_fn, remap_record_id_fn, log)
    plan["omissions.json"] = {"path": db_dir / "omissions.json", "data": data, "log": log, "collisions": []}

    plan["added_takes"] = plan_added_takes(added_files, remap_key_fn, remap_record_id_fn, make_log())

    return plan


def write_plan(db_dir: Path, plan: dict) -> Path:
    """Persist a plan built by plan_all(): backs up every file it's about to
    change into db_dir/_id_remap_backup/ first. Returns the backup dir."""
    backup_dir = db_dir / "_id_remap_backup"
    backup_dir.mkdir(exist_ok=True)

    for name in _SIDECAR_FILES + ("omissions.json",):
        entry = plan.get(name)
        if not entry or entry["data"] is None:
            continue
        path = entry["path"]
        if path.exists():
            shutil.copy2(path, backup_dir / (path.name + ".bak"))
        save(path, entry["data"])

    for f, old_obj, new_obj in plan.get("added_takes", []):
        shutil.copy2(f, backup_dir / (f.name + ".bak"))
        save(f, new_obj)

    return backup_dir


def summarize_plan(plan: dict) -> dict:
    """A JSON-friendly summary of a plan — for the /api/remap-apply response."""
    out = {"files": {}, "added_takes": []}
    for name in _SIDECAR_FILES + ("omissions.json",):
        entry = plan.get(name)
        if not entry or entry["data"] is None:
            continue
        log = entry["log"]
        out["files"][name] = {
            "remapped": len(log["remapped"]),
            "already_current": len(log["already_current"]),
            "unresolved": len(log["unresolved"]),
            "unresolved_detail": [f"{k}: {reason}" for k, reason in log["unresolved"]],
            "collisions": len(entry["collisions"]),
        }
    for f, old_obj, new_obj in plan.get("added_takes", []):
        out["added_takes"].append({
            "file": f.name,
            "record_id_from": old_obj.get("record_id", ""),
            "record_id_to": new_obj.get("record_id", ""),
        })
    return out


# ── Library entry point (used by server.py) ──────────────────────────────────

def run_remap(db_dir: Path, new_db_path: Path = None) -> dict:
    """Full fix: discover every old export, build the plan, write it (with
    backup). No interactive confirmation — the caller (the web UI's own
    confirm modal, or the CLI's input() prompt) is responsible for that.
    Returns {"summary": ..., "backup_dir": str} or raises on a hard error
    (e.g. fewer than 2 exports found)."""
    snapshots = find_db_snapshots(db_dir)
    if new_db_path is not None:
        # Caller already knows which export is "current" (e.g. server.py's
        # own cached selection) — trust it over our own mtime pick.
        snapshots = [new_db_path] + [p for p in snapshots if p != new_db_path]
    if len(snapshots) < 2:
        raise RuntimeError(
            f"Found {len(snapshots)} database export(s) in {db_dir} (and _old/) — "
            "need at least 2 (one to remap from, one current) to do anything."
        )
    new_path, old_paths = snapshots[0], snapshots[1:]
    new_db = load(new_path)
    old_dbs = [load(p) for p in old_paths]

    plan = plan_all(db_dir, new_db, old_dbs)
    backup_dir = write_plan(db_dir, plan)
    return {
        "current_export": new_path.name,
        "matched_against": [p.name for p in old_paths],
        "summary": summarize_plan(plan),
        "backup_dir": str(backup_dir),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _report_log(name: str, log: dict) -> None:
    print(f"{name}: {len(log['remapped'])} remapped, "
          f"{len(log['already_current'])} already current, "
          f"{len(log['added_take_untouched'])} added-take (untouched), "
          f"{len(log['unresolved'])} unresolved")
    for k, reason in log["unresolved"]:
        print(f"  UNRESOLVED: {k} - {reason}")


def _report_collisions(name: str, collisions: list) -> None:
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
    plan = plan_all(db_dir, new_db, old_dbs)

    for name in _SIDECAR_FILES + ("omissions.json",):
        entry = plan[name]
        if entry["data"] is None:
            continue
        _report_log(name, entry["log"])
        _report_collisions(name, entry["collisions"])

    added_updates = plan["added_takes"]
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

    backup_dir = write_plan(db_dir, plan)
    print(f"\nDone. Backups in {backup_dir}")


if __name__ == "__main__":
    main()
