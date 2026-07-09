#!/usr/bin/env python3
"""
VFX Shoot Browser — Local web server

Usage:
    python server.py                                          # default paths
    python server.py --root /path/to/project_root            # custom root
    python server.py --root /path/root --data /other/DATA    # override data dir
    python server.py --port 8080                             # custom port
    python server.py --no-browser                            # don't auto-open browser

Install dependency once:
    pip install flask
"""

import csv as _csv_mod
import io
import os
import platform
import re
import sys
import json
import shutil
import subprocess
from dataclasses import asdict
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

# Matches block directory names: J04__S01_S02__CODE__Desc
_BLOCK_RE = re.compile(
    r'^(J\d{2}|PJ\d{2})__(S\d{2}(?:_S\d{2})*)__([A-Z]{4}(?:_[A-Z]{4})*(?:_[A-Z0-9]{4})*)(?:__(.+))?$'
)

# Matches lidar directory names: CODE__Name  (CODE = 4+ uppercase letters)
_LIDAR_DIR_RE = re.compile(r'^([A-Z]{4,})__(.+)$')

try:
    from flask import Flask, jsonify, request, send_file, send_from_directory
except ImportError:
    print("\n❌ Flask is not installed.")
    print("   Run: pip install flask\n")
    sys.exit(1)

# Make sure our sibling modules are importable
sys.path.insert(0, str(Path(__file__).parent))
from generate_html import HTMLGenerator, _denormalize_json_to_rows

app = Flask(__name__)

# Resolved at startup — see _resolve_project_paths()
PROJECT_ROOT: str = ""
DATA_DIR:     str = ""
LIDAR_DIR:    str = ""
DELIVERY_DIR: str = ""
ASSETS_DIR:   str = ""

_DIR_DEFAULTS = {
    "data":              "DATA",
    "lidar":             "LIDAR",
    "delivery_packages": "DELIVERY_PACKAGES",
    "assets":            "ASSETS",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_project_config() -> dict:
    """Read project_config.json from SHOOT_BROWSER/Config/ (best-effort)."""
    cfg_path = Path(PROJECT_ROOT) / "SHOOT_BROWSER" / "Config" / "project_config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_dir(key: str, cli_val, cfg_paths: dict) -> str:
    """Priority: CLI arg > project_config.json > {PROJECT_ROOT}/{default_name}."""
    if cli_val:
        return str(Path(cli_val).resolve())
    cfg_val = (cfg_paths.get(key) or "").strip()
    if cfg_val:
        return str(Path(cfg_val).resolve())
    return str(Path(PROJECT_ROOT) / _DIR_DEFAULTS[key])


def make_generator() -> HTMLGenerator:
    """Create a fresh generator, parse directories, and return it."""
    g = HTMLGenerator(PROJECT_ROOT, data_dir=DATA_DIR, delivery_dir=DELIVERY_DIR)
    g.parse_directories()
    return g


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the browser page — data freshly scanned on every load."""
    g = make_generator()
    return g._build_html(g.build_data())


@app.route("/api/entries")
def api_entries():
    """Return all shoot entries as JSON (for future cart / package features)."""
    g = make_generator()
    return jsonify(g.build_data())


@app.route("/api/generate-html", methods=["POST"])
def api_generate_html():
    """Regenerate the static vfx_shoot_browser.html file."""
    g = make_generator()
    g.generate_html()
    return jsonify({
        "success": True,
        "path": str(g.default_output_path()),
    })


@app.route("/api/generate-offline-html", methods=["POST"])
def api_generate_offline_html():
    """Generate a fully self-contained offline HTML snapshot."""
    g = make_generator()
    out = g.generate_offline_html()
    return jsonify({"success": True, "path": out})


@app.route("/api/export-db-html", methods=["POST"])
def api_export_db_html():
    """Build a self-contained offline HTML page containing only the supplied rows."""
    try:
        body = request.json or {}
        rows = body.get("rows") or []
        g    = make_generator()
        html = g._build_html(
            g.build_data(),
            offline_data={"db_rows": rows, "delivered": [], "photos": {}},
            db_only=True,
        )
        from io import BytesIO
        buf = BytesIO(html.encode("utf-8"))
        buf.seek(0)
        return send_file(buf, mimetype="text/html",
                         as_attachment=True, download_name="database_export.html")
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/offline-site/<path:filename>")
def offline_site_file(filename):
    """Serve the generated OfflineSite directory (HTML + photos)."""
    directory = Path(PROJECT_ROOT) / "SHOOT_BROWSER" / "OfflineSite"
    return send_from_directory(str(directory), filename)


@app.route("/api/run-sanity-check", methods=["POST"])
def api_run_sanity_check():
    """Run sanity_check.py and return the captured output."""
    script = Path(__file__).parent / "sanity_check.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), PROJECT_ROOT],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
            timeout=120,
        )
        return jsonify({
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Sanity check timed out (>120s)"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _ignore_empty_dirs(src_dir, names):
    """shutil.copytree ignore callback — skip directories that contain no visible files."""
    skip = set()
    for name in names:
        full = Path(src_dir) / name
        if full.is_dir():
            has_files = any(
                f for _, _, files in os.walk(full)
                for f in files if not f.startswith(".")
            )
            if not has_files:
                skip.add(name)
    return skip


@app.route("/api/build-package", methods=["POST"])
def api_build_package():
    """Copy selected block directories into a versioned package folder."""
    body         = request.get_json() or {}
    vendor       = (body.get("vendor") or "").strip()
    package_name = (body.get("package_name") or "").strip()
    date         = (body.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    output_dir   = (body.get("output_dir") or "").strip()
    package_note = (body.get("package_note") or "").strip()
    blocks       = body.get("blocks") or []

    errors = []
    if not vendor:        errors.append("vendor is required")
    if not package_name:  errors.append("package_name is required")
    if not output_dir:    errors.append("output_dir is required")
    lidars = body.get("lidars") or []
    if not blocks and not lidars:  errors.append("no blocks or lidars selected")
    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    output_root = Path(output_dir)
    if not output_root.exists():
        return jsonify({"success": False, "errors": [f"Output directory does not exist: {output_dir}"]}), 400

    # Directory name: YYYYMMDD_package_name  (no _v01 on first delivery)
    date_compact = date.replace("-", "")
    vendor_dir   = output_root / vendor
    base_name    = f"{date_compact}_{package_name}"
    pkg_dir      = vendor_dir / base_name
    version      = 1
    if pkg_dir.exists():
        version = 2
        while (vendor_dir / f"{base_name}_v{version:02d}").exists():
            version += 1
        pkg_dir = vendor_dir / f"{base_name}_v{version:02d}"

    # Detect delivery-name collisions → fall back to original dir name
    delivery_counts: dict = {}
    for b in blocks:
        dn = b.get("delivery_name", "")
        delivery_counts[dn] = delivery_counts.get(dn, 0) + 1
    collision_names = {dn for dn, cnt in delivery_counts.items() if cnt > 1}

    try:
        pkg_dir.mkdir(parents=True, exist_ok=True)

        g_meta = HTMLGenerator(PROJECT_ROOT, data_dir=DATA_DIR)  # for subdir computation only
        copied = []
        for block in blocks:
            src  = Path(block["path"])
            dn   = block.get("delivery_name", src.name)
            note = (block.get("note") or "").strip()
            dest_name = src.name if dn in collision_names else dn
            dest = pkg_dir / dest_name

            shutil.copytree(str(src), str(dest), ignore=_ignore_empty_dirs)
            if note:
                (dest / "block_notes.txt").write_text(note, encoding="utf-8")

            subdirs = [asdict(s) for s in g_meta.get_subdir_sections(dest)]
            copied.append({"original_name": src.name, "delivery_name": dest_name, "note": note, "subdirs": subdirs})

        if package_note:
            (pkg_dir / "Package_Infos.txt").write_text(package_note, encoding="utf-8")

        # Enrich copied list with scenes/code/description from request payload
        enriched_blocks = []
        for block, c in zip(blocks, copied):
            enriched_blocks.append({
                **c,
                "scenes":      block.get("scenes", []),
                "code":        block.get("code", ""),
                "description": block.get("description", ""),
            })

        # Copy lidar directories with LIDAR__ prefix
        copied_lidars = []
        lidar_root = Path(LIDAR_DIR).resolve()
        for lidar in lidars:
            src = Path(lidar.get("path", "")).resolve()
            if not src.is_dir():
                errors.append(f"Lidar directory not found: {lidar.get('dir_name', '?')}")
                continue
            if not str(src).startswith(str(lidar_root)):
                errors.append(f"Lidar path outside LIDAR_DIR: {src}")
                continue
            dest_name = "LIDAR__" + lidar.get("dir_name", src.name)
            dest = pkg_dir / dest_name
            shutil.copytree(str(src), str(dest))
            copied_lidars.append({
                "dir_name":  lidar.get("dir_name", src.name),
                "dest_name": dest_name,
                "code":      lidar.get("code", ""),
                "name":      lidar.get("name", ""),
            })

        manifest = {
            "vendor":            vendor,
            "package_name":      package_name,
            "date":              date_compact,
            "version":           version,
            "timestamp":         datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "created_by":        "vfx_shoot_browser",
            "source_data_path":  DATA_DIR,
            "output_path":       str(pkg_dir),
            "package_note":      package_note,
            "blocks":            enriched_blocks,
            "lidars":            copied_lidars,
        }

        # package_manifest.json inside the package dir
        (pkg_dir / "package_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # __packages_infos/ at the output root — one file per delivery (for summary page)
        pkg_infos_dir = output_root / "__packages_infos"
        pkg_infos_dir.mkdir(exist_ok=True)
        info_stem = pkg_dir.name  # e.g. 20260427_poseidon_HDR_batch01
        (pkg_infos_dir / f"{info_stem}.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return jsonify({"success": True, "output_path": str(pkg_dir), "version": version})

    except Exception as e:
        if pkg_dir.exists():
            try:
                shutil.rmtree(pkg_dir)
            except Exception:
                pass
        return jsonify({"success": False, "errors": [str(e)]}), 500


@app.route("/api/delivered-packages")
def api_delivered_packages():
    """Return all delivered package manifests from DELIVERY_DIR/__packages_infos/."""
    pkg_infos_dir = Path(DELIVERY_DIR) / "__packages_infos"
    if not pkg_infos_dir.exists():
        return jsonify({"success": True, "packages": []})
    packages = []
    for f in sorted(pkg_infos_dir.glob("*.json"), reverse=True):
        try:
            packages.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify({"success": True, "packages": packages})


# ── Override helpers ──────────────────────────────────────────────────────────

def _overrides_path() -> Path:
    return Path(DATA_DIR) / "__DATABASE" / "overrides.json"


def _load_overrides() -> dict:
    p = _overrides_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "overrides": {}}


def _save_overrides(ov: dict) -> None:
    p = _overrides_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ov, indent=2, ensure_ascii=False), encoding="utf-8")


def _apply_overrides(rows: list, ov: dict) -> list:
    """Merge override values into rows; annotate each row with edit metadata."""
    ov_map = ov.get("overrides", {})
    for row in rows:
        key = row.get("_record_id", "") + "::" + row.get("_take_id", "")
        row["_override_key"] = key
        if key in ov_map:
            edited, originals = [], {}
            for field, val in ov_map[key].get("fields", {}).items():
                originals[field] = row.get(field, "")
                row[field] = val
                edited.append(field)
            row["_edited_fields"] = edited
            row["_originals"]     = originals
            row["_edited_at"]     = ov_map[key].get("edited_at", "")
        else:
            row["_edited_fields"] = []
            row["_originals"]     = {}
            row["_edited_at"]     = ""
    return rows


@app.route("/api/database")
def api_database():
    """Return database rows (with overrides applied) from __DATABASE/*.json."""
    try:
        data = _load_db_json()
        rows = _denormalize_json_to_rows(data)
        rows = _apply_overrides(rows, _load_overrides())
        rows = _apply_omissions(rows, _load_omissions())
        rows = _apply_notes(rows, _load_notes())
        return jsonify({"success": True, "rows": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/overrides/save", methods=["POST"])
def api_save_override():
    """Save field overrides for one take; optionally propagate record-level fields
    to all takes of the same record (apply_to_record=True)."""
    try:
        body             = request.json or {}
        key              = body.get("key", "")
        label            = body.get("label", "")
        fields           = body.get("fields", {})
        record_id        = body.get("record_id", "")
        apply_to_record  = body.get("apply_to_record", False)
        record_level_fields = body.get("record_level_fields", {})

        if not key:
            return jsonify({"success": False, "error": "key required"}), 400

        ov  = _load_overrides()
        ovm = ov.setdefault("overrides", {})
        now = datetime.now().isoformat(timespec="seconds")

        def _set(k, flds):
            if k not in ovm:
                ovm[k] = {"label": label, "edited_at": now, "fields": {}}
            ovm[k]["edited_at"] = now
            ovm[k]["fields"].update(flds)
            # Remove any field explicitly set to None (full revert of that field)
            ovm[k]["fields"] = {f: v for f, v in ovm[k]["fields"].items()
                                 if v is not None}
            if not ovm[k]["fields"]:
                del ovm[k]

        _set(key, fields)

        if apply_to_record and record_id and record_level_fields:
            data  = _load_db_json()
            rec_by_id = {r["id"]: r for r in data.get("records", [])
                         if r.get("id")}
            for take in data.get("takes", []):
                rec = rec_by_id.get(take.get("recordId", ""))
                if rec and rec.get("id") == record_id:
                    tkey = record_id + "::" + take.get("id", "")
                    if tkey != key:          # already handled above
                        _set(tkey, record_level_fields)

        _save_overrides(ov)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/overrides/revert", methods=["POST"])
def api_revert_override():
    """Remove all overrides for a specific take key."""
    try:
        key = (request.json or {}).get("key", "")
        ov  = _load_overrides()
        ov.get("overrides", {}).pop(key, None)
        _save_overrides(ov)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _omissions_path() -> Path:
    return Path(DATA_DIR) / "__DATABASE" / "omissions.json"


def _load_omissions() -> dict:
    p = _omissions_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "takes": [], "slates": []}


def _save_omissions(om: dict) -> None:
    p = _omissions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(om, indent=2, ensure_ascii=False), encoding="utf-8")


def _apply_omissions(rows: list, om: dict) -> list:
    """Mark each row with _omitted=True if its take or slate is omitted."""
    omit_takes  = set(om.get("takes",  []))
    omit_slates = set(om.get("slates", []))
    for row in rows:
        key = row.get("_override_key", "")
        rid = row.get("_record_id", "")
        row["_omitted"] = (key in omit_takes) or (rid in omit_slates)
    return rows


@app.route("/api/omissions/set", methods=["POST"])
def api_set_omission():
    try:
        body      = request.json or {}
        key       = body.get("key", "")
        record_id = body.get("record_id", "")
        scope     = body.get("scope", "take")   # 'take' | 'slate'
        if not key:
            return jsonify({"success": False, "error": "key required"}), 400
        om = _load_omissions()
        if scope == "slate":
            if record_id and record_id not in om["slates"]:
                om["slates"].append(record_id)
        else:
            if key not in om["takes"]:
                om["takes"].append(key)
        _save_omissions(om)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/omissions/restore", methods=["POST"])
def api_restore_omission():
    try:
        body      = request.json or {}
        key       = body.get("key", "")
        record_id = body.get("record_id", "")
        om = _load_omissions()
        om["takes"]  = [k for k in om["takes"]  if k  != key]
        om["slates"] = [k for k in om["slates"] if k  != record_id]
        _save_omissions(om)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Notes helpers ─────────────────────────────────────────────────────────────

def _notes_path() -> Path:
    return Path(DATA_DIR) / "__DATABASE" / "notes.json"


def _load_notes() -> dict:
    p = _notes_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "takes": {}}


def _save_notes(n: dict) -> None:
    p = _notes_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(n, indent=2, ensure_ascii=False), encoding="utf-8")


def _apply_notes(rows: list, notes: dict) -> list:
    """Attach user note text to each row from notes.json."""
    take_notes = notes.get("takes", {})
    for row in rows:
        key = row.get("_override_key", "")
        row["_note"] = take_notes.get(key, "")
    return rows


@app.route("/api/notes/save", methods=["POST"])
def api_save_note():
    """Save or delete a note for a specific take."""
    try:
        body = request.json or {}
        key  = body.get("key", "")
        text = (body.get("text") or "").strip()
        if not key:
            return jsonify({"success": False, "error": "key required"}), 400
        n     = _load_notes()
        takes = n.setdefault("takes", {})
        if text:
            takes[key] = text
        else:
            takes.pop(key, None)
        _save_notes(n)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


_DB_JSON_EXCLUDED = {"extraction_meta.json", "overrides.json", "omissions.json", "notes.json"}


def _load_db_json() -> dict:
    """Load the most recent JSON database export, cached in module scope."""
    db_dir = Path(DATA_DIR) / "__DATABASE"
    if not db_dir.exists():
        return {}
    jsonfiles = sorted(
        (f for f in db_dir.glob("*.json")
         if not f.name.startswith(".") and f.name not in _DB_JSON_EXCLUDED),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not jsonfiles:
        return {}
    return json.loads(jsonfiles[0].read_text(encoding="utf-8"))


@app.route("/api/database-json")
def api_database_json():
    """Return the list of slate IDs that have reference photos."""
    try:
        data = _load_db_json()
        slates_with_photos = [
            r["slateId"] for r in data.get("records", [])
            if r.get("referencePictures")
        ]
        return jsonify({"success": True, "slates_with_photos": slates_with_photos})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/database-photos/<path:slate_id>")
def api_database_photos(slate_id):
    """Return base64 photos for a specific slate ID."""
    try:
        data = _load_db_json()
        record = next(
            (r for r in data.get("records", []) if r.get("slateId") == slate_id),
            None,
        )
        if not record:
            return jsonify({"success": True, "photos": []})
        return jsonify({"success": True, "photos": record.get("referencePictures", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Slate extraction helpers ──────────────────────────────────────────────────

def _find_db_json_file() -> tuple:
    """Return (Path, date_str) for the most recent non-hidden JSON in __DATABASE/."""
    db_dir = Path(DATA_DIR) / "__DATABASE"
    if not db_dir.exists():
        return None, None
    jsonfiles = sorted(
        (f for f in db_dir.glob("*.json")
         if not f.name.startswith(".") and f.name not in _DB_JSON_EXCLUDED),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not jsonfiles:
        return None, None
    jsonfile = jsonfiles[0]
    m = re.search(r'(\d{4}-\d{2}-\d{2})', jsonfile.name)
    return jsonfile, (m.group(1) if m else None)


def _slate_scene_key(slate: str) -> str | None:
    """'18/2' → '18', '49A/1' → '49', 'P37A/3' → 'P37', 'P1/2' → 'P1'."""
    s = slate.strip()
    if s.upper().startswith('P'):
        m = re.match(r'^[Pp](\d+)', s)
        return f"P{m.group(1)}" if m else None
    m = re.match(r'^(\d+)', s)
    return m.group(1) if m else None


def _block_scene_keys(dirname: str) -> set:
    """'PJ02__S37__RIDE__x' → {'P37'}, 'J08__S08__PLAN' → {'8'}."""
    match = _BLOCK_RE.match(dirname)
    if not match:
        return set()
    is_plate = match.group(1).startswith('PJ')
    nums = {int(s[1:]) for s in match.group(2).split("_") if s.startswith("S")}
    return {f"P{n}" for n in nums} if is_plate else {str(n) for n in nums}


def _resolve_db_subdir(block_path: Path) -> Path:
    """Return the 00_Database dir inside block_path (with or without __ prefix)."""
    for name in ("00_Database", "__00_Database"):
        d = block_path / name
        if d.exists():
            return d
    return block_path / "__00_Database"


@app.route("/api/check-slates-freshness", methods=["POST"])
def api_check_slates_freshness():
    """For each block path, verify its slates CSV was generated from the current DB JSON."""
    body   = request.get_json() or {}
    blocks = body.get("blocks") or []

    jsonfile, db_date = _find_db_json_file()
    if not db_date:
        return jsonify({"success": True, "db_date": None, "stale": [], "fresh": []})

    stale, fresh = [], []
    for b in blocks:
        path   = Path(b.get("path", ""))
        name   = b.get("delivery_name") or path.name
        db_sub = _resolve_db_subdir(path)
        if (db_sub / f"slates_{db_date}.csv").exists():
            fresh.append(name)
        else:
            found = sorted(db_sub.glob("slates_*.csv")) if db_sub.exists() else []
            stale.append({
                "name":  name,
                "path":  str(path),
                "found": found[-1].name if found else None,
            })

    return jsonify({"success": True, "db_date": db_date, "stale": stale, "fresh": fresh})


def _parse_lidar_entries() -> list:
    """Scan LIDAR_DIR and return structured entry list."""
    lidar_path = Path(LIDAR_DIR)
    if not lidar_path.exists():
        return []
    entries = []
    for item in sorted(lidar_path.iterdir()):
        if not item.is_dir():
            continue
        m = _LIDAR_DIR_RE.match(item.name)
        if not m:
            continue
        code = m.group(1)
        name = m.group(2)
        all_files, previews = [], []
        try:
            for f in sorted(item.iterdir()):
                if not f.is_file() or f.name.startswith('.'):
                    continue
                if f.name.startswith('preview_') and f.suffix.lower() == '.png':
                    previews.append(f.name)
                else:
                    all_files.append({'name': f.name, 'ext': f.suffix.lower().lstrip('.')})
        except PermissionError:
            pass
        entries.append({
            'code':     code,
            'name':     name,
            'dir_name': item.name,
            'path':     str(item),
            'files':    all_files,
            'previews': previews,
        })
    return entries


@app.route("/api/lidar")
def api_lidar():
    """Return all lidar entries from LIDAR_DIR."""
    try:
        return jsonify({"success": True, "entries": _parse_lidar_entries()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/lidar-preview/<path:file_path>")
def api_lidar_preview(file_path):
    """Serve a lidar preview image (path must be inside LIDAR_DIR)."""
    from flask import send_file
    resolved = (Path(LIDAR_DIR) / file_path).resolve()
    if not str(resolved).startswith(str(Path(LIDAR_DIR).resolve())):
        return jsonify({"error": "Forbidden"}), 403
    if not resolved.is_file():
        return jsonify({"error": "Not found"}), 404
    return send_file(str(resolved), mimetype='image/png')


@app.route("/api/extract-slates-status")
def api_extract_slates_status():
    """Check whether slate extraction is up to date with the current DB JSON."""
    jsonfile, db_date = _find_db_json_file()
    if not db_date:
        return jsonify({"success": True, "db_date": None, "needs_refresh": False,
                        "filename": jsonfile.name if jsonfile else None})

    meta_path = Path(DATA_DIR) / "__DATABASE" / "extraction_meta.json"
    needs_refresh = True
    last_extracted = None
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            last_extracted = meta.get("extracted_at")
            needs_refresh = meta.get("db_date") != db_date
        except Exception:
            pass

    return jsonify({
        "success":        True,
        "db_date":        db_date,
        "filename":       jsonfile.name,
        "needs_refresh":  needs_refresh,
        "last_extracted": last_extracted,
    })


@app.route("/api/extract-slates", methods=["POST"])
def api_extract_slates():
    """Extract per-block slate CSVs from the main database JSON."""
    jsonfile, db_date = _find_db_json_file()
    if not jsonfile or not db_date:
        return jsonify({"success": False, "error": "No database JSON found"}), 400

    try:
        data = _load_db_json()
        rows = _denormalize_json_to_rows(data)
    except Exception as e:
        return jsonify({"success": False, "error": f"Could not parse JSON: {e}"}), 500
    if not rows:
        return jsonify({"success": False, "error": "No rows in JSON"}), 500
    fieldnames = list(rows[0].keys())

    updated, errors = 0, []
    skipped_blocks = []   # (block_name, scene_keys) — no matching CSV rows
    block_counts   = []   # (block_name, n_slates) — successfully extracted
    matched_keys   = set()

    for item in sorted(Path(DATA_DIR).iterdir()):
        if not item.is_dir() or not _BLOCK_RE.match(item.name):
            continue

        scene_keys = _block_scene_keys(item.name)
        if not scene_keys:
            continue

        matching = [r for r in rows
                    if _slate_scene_key(r.get("Slate", "")) in scene_keys]
        if not matching:
            skipped_blocks.append((item.name, scene_keys))
            continue

        try:
            db_sub = _resolve_db_subdir(item)

            # Rename __00_Database → 00_Database if needed (non-empty rule)
            if db_sub.name.startswith("__"):
                renamed = db_sub.parent / db_sub.name[2:]
                db_sub.mkdir(exist_ok=True)
                db_sub.rename(renamed)
                db_sub = renamed
            else:
                db_sub.mkdir(exist_ok=True)

            # Move existing slates_*.csv to history/
            existing = list(db_sub.glob("slates_*.csv"))
            if existing:
                history_dir = db_sub / "history"
                history_dir.mkdir(exist_ok=True)
                for f in existing:
                    shutil.move(str(f), str(history_dir / f.name))

            # Write new CSV
            out_path = db_sub / f"slates_{db_date}.csv"
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = _csv_mod.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(matching)

            updated += 1
            block_counts.append((item.name, len(matching)))
            matched_keys.update(
                _slate_scene_key(r.get("Slate", "")) for r in matching
            )

        except Exception as e:
            errors.append(f"{item.name}: {e}")

    all_csv_keys     = {_slate_scene_key(r.get("Slate", "")) for r in rows} - {None}
    unmatched_keys   = sorted(all_csv_keys - matched_keys)
    total_slates     = len(rows)
    extracted_slates = sum(c for _, c in block_counts)
    now              = datetime.now()
    now_str          = now.strftime("%Y-%m-%dT%H:%M:%S")
    log_suffix       = now.strftime("%Y-%m-%d_%H%M")

    # Write log file (one per run, keyed by date+hour+minute)
    log_dir  = Path(PROJECT_ROOT) / "SHOOT_BROWSER" / "Log"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"extract_slates_{log_suffix}.log"
    lines = [
        f"Slate extraction — {now_str}",
        f"Source JSON: {jsonfile.name}",
        f"DB date    : {db_date}",
        "",
        "── Summary ──────────────────────────────────────────────",
        f"  Blocks updated  : {updated}",
        f"  Blocks skipped  : {len(skipped_blocks)}  (scenes absent from JSON)",
        f"  Errors          : {len(errors)}",
        f"  Slates in CSV   : {total_slates}",
        f"  Slates extracted: {extracted_slates}",
        f"  Slates unmatched: {total_slates - extracted_slates}"
        f"  (keys with no block: {', '.join(unmatched_keys) if unmatched_keys else 'none'})",
        "",
    ]
    if skipped_blocks:
        lines.append("── Skipped blocks (scenes not in CSV) ───────────────────")
        for name, keys in skipped_blocks:
            lines.append(f"  {name}")
            lines.append(f"    scene keys: {', '.join(sorted(keys))}")
        lines.append("")
    if unmatched_keys:
        lines.append("── CSV scene keys with no matching block directory ───────")
        for key in unmatched_keys:
            count = sum(1 for r in rows if _slate_scene_key(r.get("Slate", "")) == key)
            lines.append(f"  {key:6}  ({count} slate{'s' if count != 1 else ''})")
        lines.append("")
    if block_counts:
        lines.append("── Extracted per block ───────────────────────────────────")
        for name, count in block_counts:
            lines.append(f"  {count:3}  {name}")
        lines.append("")
    if errors:
        lines.append("── Errors ────────────────────────────────────────────────")
        for e in errors:
            lines.append(f"  {e}")
        lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")

    # Save extraction metadata
    meta_path = Path(DATA_DIR) / "__DATABASE" / "extraction_meta.json"
    meta_path.write_text(json.dumps({
        "db_date":          db_date,
        "extracted_at":     now_str,
        "blocks_updated":   updated,
        "blocks_skipped":   len(skipped_blocks),
        "slates_total":     total_slates,
        "slates_extracted": extracted_slates,
        "log_file":         log_path.name,
    }, indent=2), encoding="utf-8")

    return jsonify({
        "success": True,
        "db_date": db_date,
        "updated": updated,
        "skipped": len(skipped_blocks),
        "errors":  errors,
    })


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    """Open a block directory in the native file manager."""
    path = (request.json or {}).get("path", "")
    if not path:
        return jsonify({"success": False, "error": "No path provided"}), 400
    resolved = Path(path).resolve()
    allowed_roots = [str(Path(DATA_DIR).resolve()), str(Path(LIDAR_DIR).resolve())]
    if not any(str(resolved).startswith(r) for r in allowed_roots):
        return jsonify({"success": False, "error": "Path outside allowed directories"}), 403
    if not resolved.is_dir():
        return jsonify({"success": False, "error": "Directory not found"}), 404
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(resolved)])
    elif system == "Windows":
        subprocess.run(["explorer", str(resolved)])
    else:
        subprocess.run(["xdg-open", str(resolved)])
    return jsonify({"success": True})


# ── PDF export ───────────────────────────────────────────────────────────────

PDF_INFO_FIELD_DEFAULTS = [
    'VFX ID', 'Set Location', 'Int/Ext', 'Day/Night',
    'Unit', 'Shoot Day', 'Date', 'Wrangler', 'Set Refs',
]
PDF_TAKE_COL_DEFAULTS = [
    {'field': 'Take',           'label': 'Take'},
    {'field': 'Camera',         'label': 'Camera'},
    {'field': 'Roll',           'label': 'Roll'},
    {'field': 'Lens',           'label': 'Lens'},
    {'field': 'Focal',          'label': 'Focal'},
    {'field': 'Shutter',        'label': 'Shutter'},
    {'field': 'FPS',            'label': 'FPS'},
    {'field': 'F-Stop',         'label': 'f-stop'},
    {'field': 'VFX Pass / Ref', 'label': 'VFX'},
]
PDF_TAKE_COL_WEIGHTS = {
    'Take': 1.0, 'Camera': 1.2, 'Roll': 2.2, 'Lens': 3.5, 'Focal': 1.2,
    'Shutter': 1.5, 'FPS': 1.0, 'F-Stop': 1.0, 'VFX Pass / Ref': 1.5,
    'Body': 1.5, 'Camera Move': 2.0, 'Resolution': 1.3, 'Focus': 1.1,
    'Tilt': 1.1, 'Height': 1.1, 'WB': 1.1, 'ISO': 1.1, 'Filter': 1.3,
    'Take Notes': 3.0, '_note': 3.0,
}
PDF_TAKE_COL_STYLES = {
    'Take': 'center', 'Camera': 'center', 'Focal': 'center',
    'Shutter': 'center', 'FPS': 'center', 'F-Stop': 'center',
    'Roll': 'mono', 'VFX Pass / Ref': 'vfx', 'Resolution': 'center',
    'Focus': 'center', 'Tilt': 'center', 'Height': 'center',
    'WB': 'center', 'ISO': 'center',
}

def _generate_pdf(buf, project_name: str, ordered_slates: list,
                  slate_rows: dict, records_by_slate: dict,
                  info_fields=None, take_cols=None,
                  show_vfx_work=True, show_notes=True,
                  landscape=True) -> None:
    """Render a PDF report into buf (a writable file-like object)."""
    try:
        from reportlab.lib.pagesizes import A4, landscape as _landscape
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, Image, PageBreak)
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.enums import TA_CENTER
        import base64
    except ImportError:
        raise RuntimeError(
            "reportlab is not installed. Run: pip install reportlab"
        )

    if info_fields is None:
        info_fields = PDF_INFO_FIELD_DEFAULTS
    if take_cols is None:
        take_cols = PDF_TAKE_COL_DEFAULTS

    PAGE_W, PAGE_H = _landscape(A4) if landscape else A4
    MARGIN = 18 * mm
    CW     = PAGE_W - 2 * MARGIN

    # ── Palette ───────────────────────────────────────────────────────
    NAVY   = colors.HexColor('#1a2942')
    BLUE   = colors.HexColor('#2980b9')
    BGRAY  = colors.HexColor('#f4f6f8')
    BORDER = colors.HexColor('#c8d8e8')
    GREEN  = colors.HexColor('#27ae60')
    MUTED  = colors.HexColor('#5a6a7a')
    BLACK  = colors.HexColor('#1a1a2e')
    BLUEHI = colors.HexColor('#e8f0f8')

    # ── Paragraph style factory ───────────────────────────────────────
    def _s(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=9, textColor=BLACK, leading=12)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    sty_cover_title = _s('CT', fontSize=30, fontName='Helvetica-Bold',
                          textColor=colors.white, leading=36)
    sty_cover_sub   = _s('CS', fontSize=11, textColor=colors.HexColor('#8ab4d4'))
    sty_h3          = _s('H3', fontSize=11, fontName='Helvetica-Bold', spaceAfter=3)
    sty_label       = _s('LB', fontSize=7,  fontName='Helvetica-Bold',
                          textColor=MUTED, leading=9)
    sty_value       = _s('VL', fontSize=9)
    sty_th          = _s('TH', fontSize=7.5, fontName='Helvetica-Bold',
                          textColor=colors.white, alignment=TA_CENTER)
    sty_tc          = _s('TC', fontSize=8)
    sty_tc_c        = _s('TCC', fontSize=8, alignment=TA_CENTER)
    sty_mono        = _s('MO', fontSize=7.5, fontName='Courier')
    sty_vfx         = _s('VX', fontSize=9, alignment=TA_CENTER,
                          textColor=GREEN, fontName='Helvetica-Bold')
    sty_summary     = _s('SU', fontSize=9, textColor=MUTED, fontName='Helvetica-Oblique')
    sty_note_label  = _s('NL', fontSize=7.5, fontName='Helvetica-Bold',
                          textColor=MUTED, spaceAfter=2)
    sty_note_val    = _s('NV', fontSize=8.5, leading=12)
    sty_slate_idx   = _s('SI', fontSize=8, fontName='Helvetica-Bold',
                          textColor=BLUE, alignment=TA_CENTER)

    export_date   = datetime.now().strftime('%d/%m/%Y')
    all_flat      = [r for rows in slate_rows.values() for r in rows]
    total_takes   = len(all_flat)

    # ── Document ──────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        buf, pagesize=(_landscape(A4) if landscape else A4),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=14 * mm,
        title=f"{project_name} — VFX Database Export",
    )
    story = []

    # ── Cover page ────────────────────────────────────────────────────
    cover = Table(
        [[Paragraph(project_name, sty_cover_title)],
         [Paragraph('VFX DATABASE EXPORT', sty_cover_sub)]],
        colWidths=[CW],
    )
    cover.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), NAVY),
        ('TOPPADDING',    (0,0), (-1,0),  20),
        ('BOTTOMPADDING', (0,1), (-1,1),  20),
        ('LEFTPADDING',   (0,0), (-1,-1), 20),
        ('RIGHTPADDING',  (0,0), (-1,-1), 20),
    ]))
    story.append(cover)
    story.append(Spacer(1, 10 * mm))

    cameras    = sorted({r.get('Body',  '') for r in all_flat if (r.get('Body',  '') or '').strip()})
    lenses     = sorted({r.get('Lens',  '') for r in all_flat if (r.get('Lens',  '') or '').strip()})
    dates      = sorted({r.get('Date',  '') for r in all_flat if (r.get('Date',  '') or '').strip()})
    date_range = (f"{dates[0]} — {dates[-1]}" if len(dates) > 1
                  else (dates[0] if dates else '—'))

    LW, VW = 38 * mm, CW - 38 * mm
    stat_tbl = Table([
        [Paragraph('Export date',  sty_label), Paragraph(export_date,                        sty_value)],
        [Paragraph('Slates',       sty_label), Paragraph(str(len(ordered_slates)),            sty_value)],
        [Paragraph('Takes',        sty_label), Paragraph(str(total_takes),                    sty_value)],
        [Paragraph('Cameras',      sty_label), Paragraph(', '.join(cameras) or '—',           sty_value)],
        [Paragraph('Lenses',       sty_label), Paragraph(', '.join(lenses)  or '—',           sty_value)],
        [Paragraph('Shoot dates',  sty_label), Paragraph(date_range,                          sty_value)],
    ], colWidths=[LW, VW])
    stat_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), BGRAY),
        ('GRID',       (0,0), (-1,-1), 0.5, BORDER),
        ('PADDING',    (0,0), (-1,-1), 5),
        ('VALIGN',     (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(stat_tbl)
    story.append(Spacer(1, 10 * mm))

    # Slate index grid
    story.append(Paragraph('Slates in this export', sty_h3))
    story.append(Spacer(1, 2 * mm))
    NCOLS = 8
    pad   = list(ordered_slates)
    while len(pad) % NCOLS:
        pad.append('')
    idx_tbl = Table(
        [[Paragraph(s, sty_slate_idx) for s in pad[i:i+NCOLS]]
         for i in range(0, len(pad), NCOLS)],
        colWidths=[CW / NCOLS] * NCOLS,
    )
    idx_tbl.setStyle(TableStyle([
        ('GRID',       (0,0), (-1,-1), 0.3, BORDER),
        ('PADDING',    (0,0), (-1,-1), 5),
        ('BACKGROUND', (0,0), (-1,-1), BGRAY),
    ]))
    story.append(idx_tbl)
    story.append(PageBreak())

    # ── Slate pages ───────────────────────────────────────────────────
    for slate_id in ordered_slates:
        rows   = slate_rows.get(slate_id, [])
        if not rows:
            continue
        record = records_by_slate.get(slate_id)
        first  = rows[0]

        def _v(k): return (first.get(k, '') or '').strip() or '—'

        # Slate header
        hdr = Table(
            [[Paragraph(f'SLATE  {slate_id}',
                        _s('SH', fontSize=18, fontName='Helvetica-Bold',
                           textColor=colors.white, leading=22)),
              Paragraph(_v('Scene Description'),
                        _s('SD', fontSize=10,
                           textColor=colors.HexColor('#b8d0ea'), leading=13))]],
            colWidths=[45*mm, CW - 45*mm],
        )
        hdr.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), NAVY),
            ('PADDING',    (0,0), (-1,-1), 10),
            ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(hdr)

        # Reference photos — right after header
        if record:
            pics     = (record.get('referencePictures') or [])[:4]
            img_bufs = []
            for pic in pics:
                try:
                    b64 = pic.split(',', 1)[1] if pic.startswith('data:') else pic
                    img_bufs.append(io.BytesIO(base64.b64decode(b64)))
                except Exception:
                    pass

            if img_bufs:
                n     = len(img_bufs)
                ncols = min(n, 4)
                ph_w  = (CW - (ncols - 1) * 3 * mm) / ncols
                ph_h  = 60 * mm

                ph_row = []
                for j in range(ncols):
                    try:
                        ph_row.append(Image(img_bufs[j], width=ph_w, height=ph_h, kind='bound'))
                    except Exception:
                        ph_row.append('')

                ph_tbl = Table([ph_row], colWidths=[ph_w] * ncols)
                ph_tbl.setStyle(TableStyle([
                    ('ALIGN',   (0,0), (-1,-1), 'CENTER'),
                    ('VALIGN',  (0,0), (-1,-1), 'MIDDLE'),
                    ('PADDING', (0,0), (-1,-1), 3),
                ]))
                story.append(Spacer(1, 1.5 * mm))
                story.append(ph_tbl)

        # Info grid (dynamic fields, 3 columns)
        if info_fields:
            ILW = 22 * mm
            IVW = (CW - 3 * ILW) / 3
            cells = [(f, _v(f)) for f in info_fields]
            while len(cells) % 3:
                cells.append(('', ''))
            info_rows = []
            for i in range(0, len(cells), 3):
                row = []
                for lbl, val in cells[i:i+3]:
                    row += [Paragraph(lbl, sty_label), Paragraph(val, sty_value)]
                info_rows.append(row)
            info_tbl = Table(info_rows, colWidths=[ILW, IVW] * 3)
            info_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), BGRAY),
                ('GRID',       (0,0), (-1,-1), 0.3, BORDER),
                ('PADDING',    (0,0), (-1,-1), 5),
                ('VALIGN',     (0,0), (-1,-1), 'TOP'),
            ]))
            story.append(Spacer(1, 1.5 * mm))
            story.append(info_tbl)

        # VFX Work and Notes (full-width, optional)
        text_sections = []
        if show_vfx_work: text_sections.append(('VFX Work', 'VFX Work'))
        if show_notes:    text_sections.append(('Notes', 'Notes'))
        for lbl, key in text_sections:
            text = (first.get(key, '') or '').strip()
            if text:
                ft = Table(
                    [[Paragraph(lbl, sty_note_label)],
                     [Paragraph(text, sty_note_val)]],
                    colWidths=[CW],
                )
                ft.setStyle(TableStyle([
                    ('BACKGROUND',   (0,0), (-1,-1), BGRAY),
                    ('LEFTPADDING',  (0,0), (-1,-1), 8),
                    ('RIGHTPADDING', (0,0), (-1,-1), 8),
                    ('TOPPADDING',   (0,0), (0,0),   5),
                    ('BOTTOMPADDING',(0,-1),(-1,-1),  5),
                    ('LINEBELOW',    (0,0), (-1,-1),  0.3, BORDER),
                ]))
                story.append(ft)

        # Summary line
        n_takes  = len(rows)
        bodies   = sorted({(r.get('Body') or r.get('Camera') or '').strip() for r in rows} - {''})
        lenses_u = sorted({(r.get('Lens') or '').strip() for r in rows} - {''})
        fps_u    = sorted({(r.get('FPS')  or '').strip() for r in rows} - {''})
        vfx_cnt  = sum(1 for r in rows
                       if (r.get('VFX Pass / Ref') or '').strip().lower() == 'yes')
        parts = [f'<b>{n_takes}</b> take{"s" if n_takes != 1 else ""}']
        if bodies:   parts.append(', '.join(bodies))
        if lenses_u: parts.append(', '.join(lenses_u))
        if fps_u:    parts.append(', '.join(fps_u) + ' fps')
        if vfx_cnt:  parts.append(f'<b>{vfx_cnt}</b> VFX pass{"es" if vfx_cnt != 1 else ""}')
        sum_tbl = Table([[Paragraph('  ·  '.join(parts), sty_summary)]], colWidths=[CW])
        sum_tbl.setStyle(TableStyle([
            ('BACKGROUND',  (0,0), (-1,-1), BLUEHI),
            ('PADDING',     (0,0), (-1,-1), 6),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
        ]))
        story.append(Spacer(1, 1.5 * mm))
        story.append(sum_tbl)

        # Take table (dynamic columns)
        def _sort_key(r):
            m = re.match(r'(\d+)', r.get('Take', '') or '')
            return int(m.group(1)) if m else 9999

        sorted_rows = sorted(rows, key=_sort_key)

        if take_cols:
            total_w = sum(PDF_TAKE_COL_WEIGHTS.get(c['field'], 1.5) for c in take_cols)
            tcw     = [CW * PDF_TAKE_COL_WEIGHTS.get(c['field'], 1.5) / total_w
                       for c in take_cols]

            # Row 0: slate continuation label (spans all cols); Row 1: column headers
            slate_label = Paragraph(f'SLATE  {slate_id}', _s('SRL',
                fontSize=8, fontName='Helvetica-Bold',
                textColor=colors.white, leading=11))
            take_data = [
                [slate_label] + [Paragraph('', sty_th)] * (len(take_cols) - 1),
                [Paragraph(c['label'], sty_th) for c in take_cols],
            ]
            for r in sorted_rows:
                is_vfx = (r.get('VFX Pass / Ref') or '').strip().lower() == 'yes'
                row_cells = []
                for c in take_cols:
                    f   = c['field']
                    sty = PDF_TAKE_COL_STYLES.get(f, 'normal')
                    if f == 'VFX Pass / Ref':
                        row_cells.append(Paragraph('YES' if is_vfx else '', sty_vfx))
                    elif sty == 'mono':
                        row_cells.append(Paragraph(r.get(f, '') or '—', sty_mono))
                    elif sty == 'center':
                        row_cells.append(Paragraph(r.get(f, '') or '—', sty_tc_c))
                    else:
                        row_cells.append(Paragraph(r.get(f, '') or '—', sty_tc))
                take_data.append(row_cells)

            # data rows start at index 2 (row 0 = slate label, row 1 = col headers)
            bg_cmds = [
                ('BACKGROUND', (0, i+2), (-1, i+2),
                 colors.HexColor('#edfaf2')
                 if (sorted_rows[i].get('VFX Pass / Ref') or '').strip().lower() == 'yes'
                 else (colors.white if i % 2 == 0 else BGRAY))
                for i in range(len(sorted_rows))
            ]
            take_tbl = Table(take_data, colWidths=tcw, repeatRows=2)
            take_tbl.setStyle(TableStyle([
                ('SPAN',       (0,0), (-1,0)),           # slate label spans full width
                ('BACKGROUND', (0,0), (-1,0), NAVY),     # slate label row: navy
                ('BACKGROUND', (0,1), (-1,1), BLUE),     # column header row: blue
                ('GRID',       (0,0), (-1,-1), 0.3, BORDER),
                ('PADDING',    (0,0), (-1,-1), 4),
                ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
            ] + bg_cmds))
            story.append(Spacer(1, 1.5 * mm))
            story.append(take_tbl)

        story.append(PageBreak())

    # ── Footer on every page ──────────────────────────────────────────
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, 8 * mm, project_name)
        canvas.drawCentredString(PAGE_W / 2, 8 * mm, export_date)
        canvas.drawRightString(PAGE_W - MARGIN, 8 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


@app.route("/api/export-pdf", methods=["POST"])
def api_export_pdf():
    """Generate and stream a PDF report for the requested slate IDs."""
    try:
        body          = request.json or {}
        slate_ids     = body.get("slates") or []
        take_ids      = body.get("take_ids")       # None = all takes; list = filtered
        info_fields   = body.get("info_fields") or PDF_INFO_FIELD_DEFAULTS
        take_cols     = body.get("take_cols")   or PDF_TAKE_COL_DEFAULTS
        show_vfx_work = body.get("show_vfx_work", True)
        show_notes    = body.get("show_notes",    True)
        pdf_landscape = body.get("landscape",     True)

        data             = _load_db_json()
        all_rows         = _denormalize_json_to_rows(data)
        all_rows         = _apply_overrides(all_rows, _load_overrides())
        all_rows         = _apply_notes(all_rows, _load_notes())
        records_by_slate = {r["slateId"]: r for r in data.get("records", [])}
        project_name     = (data.get("project") or {}).get("name", "VFX Shoot")

        def _base(s):
            return re.sub(r'/\d+$', '', (s or '').strip())

        # Build take filter set when scope = filtered
        take_set = None
        if take_ids is not None:
            take_set = {(t["slate"], t["take"], t["camera"]) for t in take_ids}

        slate_rows = {sid: [] for sid in slate_ids}
        for row in all_rows:
            base = _base(row.get("Slate", ""))
            if base not in slate_rows:
                continue
            if take_set is not None:
                key = (row.get("Slate",""), row.get("Take",""), row.get("Camera",""))
                if key not in take_set:
                    continue
            slate_rows[base].append(row)

        buf = io.BytesIO()
        _generate_pdf(buf, project_name, slate_ids, slate_rows, records_by_slate,
                      info_fields=info_fields, take_cols=take_cols,
                      show_vfx_work=show_vfx_work, show_notes=show_notes,
                      landscape=pdf_landscape)
        buf.seek(0)

        safe     = re.sub(r'[^\w\-.]', '_', project_name)
        filename = f"{safe}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(buf, mimetype="application/pdf",
                         as_attachment=True, download_name=filename)

    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ── Startup ───────────────────────────────────────────────────────────────────

def _open_browser(port: int) -> None:
    """Open the browser 1 second after the server starts."""
    import time
    time.sleep(1.0)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="VFX Shoot Browser — Local web server")
    parser.add_argument(
        "--root",
        default="/Volumes/MACGUFF001/POSEIDON/SHOOT_BROWSER",
        help="Project root directory (contains DATA/, SHOOT_BROWSER/, LIDAR/, …)",
    )
    parser.add_argument("--data",     default=None, help="Override DATA directory path")
    parser.add_argument("--lidar",    default=None, help="Override LIDAR directory path")
    parser.add_argument("--asset",    default=None, help="Override ASSETS directory path")
    parser.add_argument("--delivery-packages", default=None, dest="delivery_packages",
                        help="Override DELIVERY_PACKAGES directory path")
    parser.add_argument("--port",       type=int, default=5001, help="Port (default: 5001)")
    parser.add_argument("--no-browser", action="store_true",    help="Do not open browser automatically")
    args = parser.parse_args()

    global PROJECT_ROOT, DATA_DIR, LIDAR_DIR, DELIVERY_DIR, ASSETS_DIR
    PROJECT_ROOT = str(Path(args.root).resolve())
    cfg          = _load_project_config()
    cfg_paths    = cfg.get("paths", {})
    DATA_DIR     = _resolve_dir("data",              args.data,               cfg_paths)
    LIDAR_DIR    = _resolve_dir("lidar",             args.lidar,              cfg_paths)
    DELIVERY_DIR = _resolve_dir("delivery_packages", args.delivery_packages,  cfg_paths)
    ASSETS_DIR   = _resolve_dir("assets",            args.asset,              cfg_paths)

    print("\n" + "=" * 60)
    print("🎬  VFX SHOOT BROWSER — Local Server")
    print("=" * 60)
    _db_file, _ = _find_db_json_file()
    _db_label   = str(_db_file) if _db_file else "— not found —"
    print(f"  Root     : {PROJECT_ROOT}")
    print(f"  Data     : {DATA_DIR}")
    print(f"  Database : {_db_label}")
    print(f"  Delivery : {DELIVERY_DIR}")
    print(f"  Lidar    : {LIDAR_DIR}")
    print(f"  Assets   : {ASSETS_DIR}")
    print(f"  URL      : http://127.0.0.1:{args.port}")
    print(f"\n  Press Ctrl+C to stop the server.")
    print("=" * 60 + "\n")

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(args.port,), daemon=True).start()

    app.run(host="127.0.0.1", port=args.port, debug=True)


if __name__ == "__main__":
    main()
