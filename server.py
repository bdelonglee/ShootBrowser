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

import sys
import subprocess
import threading
import webbrowser
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
