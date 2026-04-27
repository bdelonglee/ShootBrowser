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

import os
import sys
import json
import shutil
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, jsonify, request
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

            copied.append({"original_name": src.name, "delivery_name": dest_name, "note": note})

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
