#!/usr/bin/env python3
"""
VFX Shoot Browser — Local web server

Usage:
    python server.py                              # default data path
    python server.py --data-path /path/to/data   # custom data path
    python server.py --port 8080                 # custom port
    python server.py --no-browser                # don't auto-open browser

Install dependency once:
    pip install flask
"""

import csv as _csv_mod
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

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("\n❌ Flask is not installed.")
    print("   Run: pip install flask\n")
    sys.exit(1)

# Make sure our sibling modules are importable
sys.path.insert(0, str(Path(__file__).parent))
from generate_html import HTMLGenerator

app = Flask(__name__)
DATA_PATH: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_generator() -> HTMLGenerator:
    """Create a fresh generator, parse directories, and return it."""
    g = HTMLGenerator(DATA_PATH)
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


@app.route("/offline-site/<path:filename>")
def offline_site_file(filename):
    """Serve the generated OfflineSite directory (HTML + photos)."""
    directory = Path(DATA_PATH) / "__SHOOT_BROWSER" / "OfflineSite"
    return send_from_directory(str(directory), filename)


@app.route("/api/run-sanity-check", methods=["POST"])
def api_run_sanity_check():
    """Run sanity_check.py and return the captured output."""
    script = Path(__file__).parent / "sanity_check.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), DATA_PATH],
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
    if not blocks:        errors.append("no blocks selected")
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

        g_meta = HTMLGenerator(DATA_PATH)  # for subdir computation only
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

        manifest = {
            "vendor":            vendor,
            "package_name":      package_name,
            "date":              date_compact,
            "version":           version,
            "timestamp":         datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "created_by":        "vfx_shoot_browser",
            "source_data_path":  DATA_PATH,
            "output_path":       str(pkg_dir),
            "package_note":      package_note,
            "blocks":            enriched_blocks,
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
    """Return all delivered package manifests from __packages_infos/."""
    cfg_path = Path(DATA_PATH) / "__SHOOT_BROWSER" / "Config" / "delivery_config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

    output_dir = (cfg.get("default_output_dir") or "").strip()
    if not output_dir:
        return jsonify({"success": True, "packages": [],
                        "warning": "No default_output_dir in delivery_config.json"})

    pkg_infos_dir = Path(output_dir) / "__packages_infos"
    if not pkg_infos_dir.exists():
        return jsonify({"success": True, "packages": []})

    packages = []
    for f in sorted(pkg_infos_dir.glob("*.json"), reverse=True):
        try:
            packages.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass

    return jsonify({"success": True, "packages": packages})


@app.route("/api/database")
def api_database():
    """Return CSV rows from __DATABASE/*.csv (most recent file by mtime)."""
    import csv as csv_mod
    db_dir = Path(DATA_PATH) / "__DATABASE"
    if not db_dir.exists():
        return jsonify({"success": True, "rows": [], "filename": None})
    csvfiles = sorted(
        (f for f in db_dir.glob("*.csv") if not f.name.startswith(".")),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not csvfiles:
        return jsonify({"success": True, "rows": [], "filename": None})
    csvfile = csvfiles[0]
    rows = []
    for encoding in ("mac_roman", "utf-8-sig", "latin-1"):
        try:
            with open(csvfile, encoding=encoding, newline="") as f:
                reader = csv_mod.DictReader(f)
                rows = [{k: (v or "").strip() for k, v in row.items() if k is not None}
                        for row in reader]
            break
        except UnicodeDecodeError:
            rows = []
    return jsonify({"success": True, "rows": rows, "filename": csvfile.name})


def _load_db_json() -> dict:
    """Load the most recent JSON database export, cached in module scope."""
    db_dir = Path(DATA_PATH) / "__DATABASE"
    if not db_dir.exists():
        return {}
    jsonfiles = sorted(
        (f for f in db_dir.glob("*.json") if not f.name.startswith(".")),
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

def _find_db_csv() -> tuple:
    """Return (Path, date_str) for the most recent non-hidden CSV in __DATABASE/."""
    db_dir = Path(DATA_PATH) / "__DATABASE"
    if not db_dir.exists():
        return None, None
    csvfiles = sorted(
        (f for f in db_dir.glob("*.csv") if not f.name.startswith(".")),
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    if not csvfiles:
        return None, None
    csvfile = csvfiles[0]
    m = re.search(r'(\d{4}-\d{2}-\d{2})', csvfile.name)
    return csvfile, (m.group(1) if m else None)


def _load_db_csv(csvfile: Path) -> tuple:
    """Return (fieldnames, rows) parsed from csvfile, trying multiple encodings."""
    for encoding in ("mac_roman", "utf-8-sig", "latin-1"):
        try:
            with open(csvfile, encoding=encoding, newline="") as f:
                reader = _csv_mod.DictReader(f)
                fieldnames = list(reader.fieldnames or [])
                rows = [dict(r) for r in reader]
            return fieldnames, rows
        except UnicodeDecodeError:
            pass
    return [], []


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


@app.route("/api/extract-slates-status")
def api_extract_slates_status():
    """Check whether slate extraction is up to date with the current DB CSV."""
    csvfile, db_date = _find_db_csv()
    if not db_date:
        return jsonify({"success": True, "db_date": None, "needs_refresh": False,
                        "filename": csvfile.name if csvfile else None})

    meta_path = Path(DATA_PATH) / "__DATABASE" / "extraction_meta.json"
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
        "filename":       csvfile.name,
        "needs_refresh":  needs_refresh,
        "last_extracted": last_extracted,
    })


@app.route("/api/extract-slates", methods=["POST"])
def api_extract_slates():
    """Extract per-block slate CSVs from the main database CSV."""
    csvfile, db_date = _find_db_csv()
    if not csvfile or not db_date:
        return jsonify({"success": False, "error": "No database CSV found"}), 400

    fieldnames, rows = _load_db_csv(csvfile)
    if not rows:
        return jsonify({"success": False, "error": "Could not parse CSV"}), 500

    updated, errors = 0, []
    skipped_blocks = []   # (block_name, scene_keys) — no matching CSV rows
    block_counts   = []   # (block_name, n_slates) — successfully extracted
    matched_keys   = set()

    for item in sorted(Path(DATA_PATH).iterdir()):
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
    log_dir  = Path(DATA_PATH) / "__SHOOT_BROWSER" / "Log"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"extract_slates_{log_suffix}.log"
    lines = [
        f"Slate extraction — {now_str}",
        f"Source CSV : {csvfile.name}",
        f"DB date    : {db_date}",
        "",
        "── Summary ──────────────────────────────────────────────",
        f"  Blocks updated  : {updated}",
        f"  Blocks skipped  : {len(skipped_blocks)}  (scenes absent from CSV)",
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
    meta_path = Path(DATA_PATH) / "__DATABASE" / "extraction_meta.json"
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
    if not str(resolved).startswith(str(Path(DATA_PATH).resolve())):
        return jsonify({"success": False, "error": "Path outside data directory"}), 403
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
        "--data-path",
        default="/Volumes/MACGUFF001/POSEIDON/DATA",
        help="Path to the shoot data directory",
    )
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    global DATA_PATH
    DATA_PATH = args.data_path

    print("\n" + "=" * 60)
    print("🎬  VFX SHOOT BROWSER — Local Server")
    print("=" * 60)
    print(f"  Data path : {DATA_PATH}")
    print(f"  URL       : http://127.0.0.1:{args.port}")
    print(f"\n  Press Ctrl+C to stop the server.")
    print("=" * 60 + "\n")

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(args.port,), daemon=True).start()

    app.run(host="127.0.0.1", port=args.port, debug=True)


if __name__ == "__main__":
    main()
