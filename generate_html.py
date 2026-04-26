#!/usr/bin/env python3
"""
VFX Shoot Data HTML Generator
Generates an interactive HTML page to browse shoot data by days, scenes, or codes
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
from datetime import datetime


@dataclass
class SubdirChild:
    name: str
    count: int  # file count inside that directory


@dataclass
class SubdirSection:
    name: str
    kind: str        # 'nested' | 'count' | 'simple'
    children: List[SubdirChild]  # for 'nested'
    count: int       # for 'count' (-1 otherwise)


@dataclass
class ShootEntry:
    path: str
    directory_name: str
    day: str
    scenes: List[str]
    code: str
    description: str
    has_data: bool
    subdirs: List[SubdirSection]


class HTMLGenerator:

    DIR_PATTERN = re.compile(
        r'^(J\d{2}|PJ\d{2})__(S\d{2}(?:_S\d{2})*)__([A-Z]{4}(?:_[A-Z]{4})*)__(.+)$'
    )

    DEFAULT_SKIP_DIRS   = {'TODO__', '__RAPPORTS_SCRIPT', '__Souvenirs_Vrac', '__CALLSHEETS'}
    DEFAULT_TEMPLATE_DIR = 'J00_TEMPLATE'
    DEFAULT_HDR_SUBDIRS  = {'Fisheye': 'F', 'Theta': 'T', 'Theta_Underwater': 'U'}
    CONFIG_PATH = '__SHOOT_BROWSER/Config/sanity_check.json'

    # Subdirectory display modes (matched against non-__ subdir names)
    HDR_DIRS         = {'20_HDR'}
    NESTED_FLAT_DIRS = {'32_Photog_Photos', '40_Photos', '50_Videos',
                        '30_Photog_Polycam', '31_Photog_Scale', '70_Temoin_Videos'}
    COUNT_ONLY_DIRS  = {'60_Temoin_Photos'}
    LIST_FILES_DIRS  = {'10_Infos', '00_Database', '80_References'}

    def __init__(self, data_path: str):
        self.data_path = Path(data_path).resolve()
        self.entries: List[ShootEntry] = []
        self._load_config()

    def _load_config(self) -> None:
        config_path = self.data_path / self.CONFIG_PATH
        config = {}
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print(f"⚙️  Config loaded: {config_path}")
            except Exception as e:
                print(f"⚠️  Could not load config ({e}), using defaults")
        self.skip_dirs       = set(config.get('skip_dirs', self.DEFAULT_SKIP_DIRS))
        self.template_dir    = config.get('template_dir', self.DEFAULT_TEMPLATE_DIR)
        self.hdr_subdir_names = list(
            config.get('hdr_subdirs', self.DEFAULT_HDR_SUBDIRS).keys()
        )

    def default_output_path(self) -> Path:
        return self.data_path / '__SHOOT_BROWSER' / 'vfx_shoot_browser.html'

    # ── File counting ────────────────────────────────────────────────────────

    def count_files_direct(self, dir_path: Path) -> int:
        """Count visible files directly inside dir_path (non-recursive)."""
        count = 0
        try:
            for f in dir_path.iterdir():
                if f.is_file() and not f.name.startswith('.'):
                    count += 1
        except PermissionError:
            pass
        return count

    def count_files_recursive(self, dir_path: Path) -> int:
        """Count all visible files inside dir_path (recursive)."""
        count = 0
        try:
            for root, dirs, files in os.walk(dir_path):
                count += sum(1 for f in files if not f.startswith('.'))
        except PermissionError:
            pass
        return count

    def check_has_data(self, dir_path: Path) -> bool:
        for root, dirs, files in os.walk(dir_path):
            if any(not f.startswith('.') for f in files):
                return True
        return False

    # ── Subdirectory analysis ────────────────────────────────────────────────

    def _hdr_children(self, hdr_dir: Path) -> List[SubdirChild]:
        """List grandchildren of 20_HDR (through Fisheye / Theta / etc.)."""
        children = []
        for type_name in self.hdr_subdir_names:
            for prefix in ['__', '']:
                candidate = hdr_dir / (prefix + type_name)
                if candidate.exists() and candidate.is_dir():
                    try:
                        for grandchild in sorted(candidate.iterdir()):
                            if grandchild.is_dir() and not grandchild.name.startswith('.'):
                                children.append(
                                    SubdirChild(grandchild.name,
                                                self.count_files_recursive(grandchild))
                                )
                    except PermissionError:
                        pass
                    break
        return children

    def _nested_flat_children(self, dir_path: Path) -> List[SubdirChild]:
        """List direct non-empty child subdirs with their recursive file counts."""
        children = []
        try:
            for child in sorted(dir_path.iterdir()):
                if child.is_dir() and not child.name.startswith('.'):
                    fc = self.count_files_recursive(child)
                    if fc > 0:
                        children.append(SubdirChild(child.name, fc))
        except PermissionError:
            pass
        return children

    def _list_files(self, dir_path: Path) -> List[SubdirChild]:
        """List visible files directly inside dir_path (count field unused, set to -1)."""
        files = []
        try:
            for f in sorted(dir_path.iterdir()):
                if f.is_file() and not f.name.startswith('.'):
                    files.append(SubdirChild(f.name, -1))
        except PermissionError:
            pass
        return files

    def get_subdir_sections(self, dir_path: Path) -> List[SubdirSection]:
        """
        Return structured display info for every non-__ immediate subdirectory.
        __ prefix → considered empty → skipped.
        """
        sections = []
        simple_names = []
        try:
            for item in sorted(dir_path.iterdir(), key=lambda x: x.name):
                if not item.is_dir():
                    continue
                if item.name.startswith('__') or item.name.startswith('.'):
                    continue

                name = item.name

                if name in self.HDR_DIRS:
                    children = self._hdr_children(item)
                    if children:
                        sections.append(SubdirSection(name, 'nested', children, -1))

                elif name in self.NESTED_FLAT_DIRS:
                    children = self._nested_flat_children(item)
                    if children:
                        sections.append(SubdirSection(name, 'nested', children, -1))
                    else:
                        # No subdirs — fall back to direct file count
                        fc = self.count_files_direct(item)
                        sections.append(SubdirSection(name, 'count', [], fc))

                elif name in self.COUNT_ONLY_DIRS:
                    fc = self.count_files_direct(item)
                    sections.append(SubdirSection(name, 'count', [], fc))

                elif name in self.LIST_FILES_DIRS:
                    files = self._list_files(item)
                    if files:
                        sections.append(SubdirSection(name, 'files', files, -1))

                else:
                    simple_names.append(name)

        except PermissionError:
            pass

        # Append all "simple" names as a single section so they render as tags
        if simple_names:
            sections.append(SubdirSection('__other__', 'simple',
                                          [SubdirChild(n, -1) for n in simple_names], -1))
        return sections

    # ── Directory parsing ────────────────────────────────────────────────────

    def parse_directories(self):
        print("📂 Parsing shoot directories...")
        for item in sorted(self.data_path.iterdir()):
            if not item.is_dir():
                continue
            if any(skip in item.name for skip in self.skip_dirs):
                continue
            if item.name == self.template_dir:
                continue
            match = self.DIR_PATTERN.match(item.name)
            if not match:
                continue

            day        = match.group(1)
            scenes_str = match.group(2)
            code       = match.group(3)
            description = match.group(4)

            self.entries.append(ShootEntry(
                path=str(item),
                directory_name=item.name,
                day=day,
                scenes=scenes_str.split('_'),
                code=code,
                description=description,
                has_data=self.check_has_data(item),
                subdirs=self.get_subdir_sections(item),
            ))

        print(f"   Found {len(self.entries)} shoot entries")

    # ── Data organisation ────────────────────────────────────────────────────

    def organize_by_days(self) -> Dict[str, List[ShootEntry]]:
        by_day = defaultdict(list)
        for e in self.entries:
            by_day[e.day].append(e)
        return dict(sorted(by_day.items()))

    def organize_by_scenes(self) -> Dict[str, List[ShootEntry]]:
        by_scene = defaultdict(list)
        for e in self.entries:
            for scene in e.scenes:
                by_scene[scene].append(e)
        return dict(sorted(by_scene.items()))

    def organize_by_codes(self) -> Dict[str, List[ShootEntry]]:
        by_code = defaultdict(list)
        for e in self.entries:
            for code in e.code.split('_'):
                by_code[code].append(e)
        return dict(sorted(by_code.items()))

    # ── HTML generation ──────────────────────────────────────────────────────

    def generate_html(self, output_path: Optional[str] = None):
        print("🎨 Generating HTML page...")
        out = Path(output_path) if output_path else self.default_output_path()
        out.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'by_days':   {k: [asdict(e) for e in v] for k, v in self.organize_by_days().items()},
            'by_scenes': {k: [asdict(e) for e in v] for k, v in self.organize_by_scenes().items()},
            'by_codes':  {k: [asdict(e) for e in v] for k, v in self.organize_by_codes().items()},
        }

        with open(out, 'w', encoding='utf-8') as f:
            f.write(self._build_html(data))

        print(f"   Saved to: {out}")

    def _build_html(self, data: dict) -> str:
        data_json      = json.dumps(data, indent=2)
        generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VFX Shoot Data Browser</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            --bg:           #0d1117;
            --surface:      #161b22;
            --surface-2:    #1c2128;
            --surface-3:    #22272e;
            --border:       rgba(175,184,193,0.12);
            --border-hover: rgba(175,184,193,0.22);
            --text:         #cdd9e5;
            --text-muted:   #768390;
            --accent:       #4493f8;
            --accent-glow:  rgba(68,147,248,0.15);
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 24px 20px;
            min-height: 100vh;
        }}

        .container {{ max-width: 1400px; margin: 0 auto; }}

        /* ── Header ── */
        header {{
            padding: 28px 0 20px;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}
        h1 {{
            font-size: 1.8em;
            font-weight: 700;
            color: var(--text);
            letter-spacing: -0.02em;
            margin-bottom: 4px;
        }}
        .subtitle {{ color: var(--text-muted); font-size: 0.9em; }}

        /* ── Controls ── */
        .controls {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 14px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }}

        .mode-button {{
            background: var(--surface-2);
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 8px 18px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.88em;
            font-weight: 600;
            transition: all 0.15s;
            white-space: nowrap;
        }}
        .mode-button:hover {{
            border-color: var(--accent);
            color: var(--accent);
            background: var(--accent-glow);
        }}
        .mode-button.active {{
            background: var(--accent-glow);
            border-color: var(--accent);
            color: var(--accent);
        }}

        /* ── Search ── */
        .search-wrapper {{
            position: relative;
            flex: 1;
            min-width: 200px;
            max-width: 400px;
        }}
        .search-icon {{
            position: absolute;
            left: 11px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            pointer-events: none;
            font-size: 0.9em;
        }}
        #search-input {{
            width: 100%;
            padding: 8px 34px;
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-size: 0.9em;
            outline: none;
            transition: border-color 0.15s;
        }}
        #search-input::placeholder {{ color: var(--text-muted); }}
        #search-input:focus {{ border-color: var(--accent); }}
        #search-clear {{
            position: absolute;
            right: 9px;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            cursor: pointer;
            color: var(--text-muted);
            font-size: 1em;
            display: none;
            line-height: 1;
        }}
        #search-clear:hover {{ color: var(--text); }}

        /* ── Stats ── */
        .stats {{ margin-left: auto; display: flex; gap: 24px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 1.5em; font-weight: 700; color: var(--accent); }}
        .stat-label {{ font-size: 0.75em; color: var(--text-muted); margin-top: 1px; }}

        /* ── Search info ── */
        #search-info {{
            background: var(--accent-glow);
            border: 1px solid rgba(68,147,248,0.25);
            border-radius: 6px;
            padding: 7px 14px;
            margin-bottom: 12px;
            font-size: 0.85em;
            color: var(--accent);
            display: none;
        }}

        /* ── Content ── */
        .content {{
            min-height: 400px;
        }}

        /* ── Groups ── */
        .group {{ margin-bottom: 24px; }}
        .group-header {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-left: 3px solid var(--accent);
            color: var(--text);
            padding: 11px 16px;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 700;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            letter-spacing: 0.01em;
        }}
        .group-count {{
            background: var(--surface-2);
            border: 1px solid var(--border);
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.75em;
            color: var(--text-muted);
            font-weight: 500;
        }}

        /* ── Entry cards ── */
        .entry {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-left: 3px solid transparent;
            padding: 14px 16px;
            margin-bottom: 8px;
            border-radius: 8px;
            transition: all 0.15s;
        }}
        .entry:hover {{
            background: var(--surface-2);
            border-color: var(--border-hover);
            border-left-color: var(--accent);
            transform: translateX(3px);
        }}

        /* ── Entry title line ── */
        .entry-title-line {{
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }}
        .title-day, .title-scene, .title-code, .title-desc {{
            display: inline-block;
            padding: 3px 9px;
            border-radius: 6px;
            font-weight: 600;
        }}
        .title-day {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.8em;
            background: rgba(86,211,100,0.12);
            color: #56d364;
            border: 1px solid rgba(86,211,100,0.2);
        }}
        .title-scene {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.8em;
            background: rgba(57,197,207,0.12);
            color: #39c5cf;
            border: 1px solid rgba(57,197,207,0.2);
        }}
        .title-code {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.8em;
            background: rgba(227,179,65,0.12);
            color: #e3b341;
            border: 1px solid rgba(227,179,65,0.2);
        }}
        .title-desc {{
            font-size: 0.95em;
            background: rgba(68,147,248,0.12);
            color: #7eb8f7;
            border: 1px solid rgba(68,147,248,0.2);
        }}
        .badge-no-data {{
            background: rgba(248,81,73,0.15);
            color: #f85149;
            border: 1px solid rgba(248,81,73,0.3);
            padding: 3px 9px;
            border-radius: 6px;
            font-size: 0.78em;
            font-weight: 600;
        }}

        mark {{
            background: rgba(210,153,34,0.35);
            color: #e3b341;
            border-radius: 2px;
            padding: 0 1px;
        }}

        /* ── Subdirectory sections ── */
        .subdir-sections {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .subdir-section-label {{
            font-size: 0.72em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--text-muted);
            margin-bottom: 5px;
        }}
        .subdir-children {{
            display: flex;
            flex-direction: column;
            gap: 3px;
        }}
        .subdir-child {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 5px;
            padding: 4px 10px;
            font-size: 0.8em;
            font-family: 'Monaco', 'Courier New', monospace;
            color: var(--text);
        }}
        .subdir-child-count {{
            color: var(--text-muted);
            font-size: 0.9em;
            margin-left: 12px;
            white-space: nowrap;
        }}

        .subdir-count-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85em;
        }}
        .subdir-count-name {{
            font-weight: 600;
            color: var(--text);
        }}

        .subdir-file {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 3px 10px;
            font-size: 0.8em;
            font-family: 'Monaco', 'Courier New', monospace;
            color: var(--text-muted);
        }}

        .subdir-simple-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
        }}
        .subdir-simple-item {{
            background: var(--surface-2);
            border: 1px solid var(--border);
            padding: 3px 9px;
            border-radius: 5px;
            font-size: 0.8em;
            font-family: 'Monaco', 'Courier New', monospace;
            color: var(--text-muted);
        }}

        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }}
        .empty-state-icon {{ font-size: 3em; margin-bottom: 16px; }}

        footer {{
            text-align: center;
            margin-top: 28px;
            color: var(--text-muted);
            font-size: 0.8em;
        }}

        @media (max-width: 768px) {{
            .stats {{ margin-left: 0; width: 100%; }}
            .search-wrapper {{ max-width: 100%; }}
        }}
    </style>
</head>
<body>
<div class="container">

    <header>
        <h1>VFX Shoot Browser</h1>
        <p class="subtitle">POSEIDON — Browse shoot data by days, scenes, or codes</p>
    </header>

    <div class="controls">
        <button class="mode-button active" onclick="setMode('days')"   id="btn-days">📅 By Days</button>
        <button class="mode-button"        onclick="setMode('scenes')" id="btn-scenes">🎞️ By Scenes</button>
        <button class="mode-button"        onclick="setMode('codes')"  id="btn-codes">🏷️ By Codes</button>

        <div class="search-wrapper">
            <span class="search-icon">🔍</span>
            <input id="search-input" type="text"
                   placeholder="Search day, scene, code, description…"
                   oninput="onSearch(this.value)">
            <button id="search-clear" onclick="clearSearch()" title="Clear">✕</button>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="stat-total">0</div>
                <div class="stat-label">Entries</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="stat-groups">0</div>
                <div class="stat-label">Groups</div>
            </div>
        </div>
    </div>

    <div id="search-info"></div>

    <div class="content" id="content">
        <div class="empty-state">
            <div class="empty-state-icon">📂</div>
            <p>Loading…</p>
        </div>
    </div>

    <footer>Generated on {generated_time}</footer>

</div>
<script>
const data = {data_json};

let currentMode  = 'days';
let currentQuery = '';

// ── Mode ─────────────────────────────────────────────────────────────────────

function setMode(mode) {{
    currentMode = mode;
    document.querySelectorAll('.mode-button').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-${{mode}}`).classList.add('active');
    render();
}}

// ── Search ───────────────────────────────────────────────────────────────────

function onSearch(value) {{
    currentQuery = value.trim().toLowerCase();
    document.getElementById('search-clear').style.display = currentQuery ? 'block' : 'none';
    render();
}}

function clearSearch() {{
    document.getElementById('search-input').value = '';
    onSearch('');
}}

function entryMatches(entry, q) {{
    if (!q) return true;
    const haystack = [
        entry.day,
        entry.code,
        entry.description.replace(/_/g, ' '),
        entry.directory_name,
        ...entry.scenes,
        ...entry.code.split('_'),
    ].join(' ').toLowerCase();
    return q.split(/\\s+/).every(w => haystack.includes(w));
}}

function highlight(text, q) {{
    const safe = escHtml(text);
    if (!q) return safe;
    const words = q.split(/\\s+/).filter(Boolean);
    if (!words.length) return safe;
    const pat = new RegExp(`(${{words.map(escRe).join('|')}})`, 'gi');
    return safe.replace(pat, '<mark>$1</mark>');
}}

function escHtml(s) {{
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
function escRe(s) {{
    return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
}}

// ── Subdirectory rendering ───────────────────────────────────────────────────

function renderSubdirs(subdirs) {{
    if (!subdirs || subdirs.length === 0) return '';

    let parts = '';

    for (const s of subdirs) {{
        if (s.kind === 'nested') {{
            const rows = s.children.map(c =>
                `<div class="subdir-child">
                    <span>${{escHtml(c.name)}}</span>
                    <span class="subdir-child-count">${{c.count}}</span>
                </div>`
            ).join('');
            parts += `<div class="subdir-section">
                <div class="subdir-section-label">📁 ${{escHtml(s.name)}}</div>
                <div class="subdir-children">${{rows}}</div>
            </div>`;

        }} else if (s.kind === 'count') {{
            parts += `<div class="subdir-count-row">
                <span class="subdir-count-name">📁 ${{escHtml(s.name)}}</span>
                <span class="subdir-child-count">(${{s.count}} files)</span>
            </div>`;

        }} else if (s.kind === 'files') {{
            const rows = s.children.map(c =>
                `<div class="subdir-file">📄 ${{escHtml(c.name)}}</div>`
            ).join('');
            parts += `<div class="subdir-section">
                <div class="subdir-section-label">📁 ${{escHtml(s.name)}}</div>
                <div class="subdir-children">${{rows}}</div>
            </div>`;

        }} else if (s.kind === 'simple') {{
            const tags = s.children.map(c =>
                `<span class="subdir-simple-item">${{escHtml(c.name)}}</span>`
            ).join('');
            parts += `<div class="subdir-simple-group">${{tags}}</div>`;
        }}
    }}

    return `<div class="subdir-sections">${{parts}}</div>`;
}}

// ── Entry rendering ───────────────────────────────────────────────────────────

function renderEntry(entry, q) {{
    const dayHtml    = `<span class="title-day">${{highlight(entry.day, q)}}</span>`;
    const scenesHtml = entry.scenes.map(s =>
        `<span class="title-scene">${{highlight(s, q)}}</span>`
    ).join('');
    const codesHtml  = entry.code.split('_').map(c =>
        `<span class="title-code">${{highlight(c, q)}}</span>`
    ).join('');
    const descHtml   = `<span class="title-desc">${{highlight(entry.description.replace(/_/g,' '), q)}}</span>`;
    const noData     = entry.has_data ? '' : '<span class="badge-no-data">No Data</span>';

    return `<div class="entry">
        <div class="entry-title-line">
            ${{dayHtml}}${{scenesHtml}}${{codesHtml}}${{descHtml}}${{noData}}
        </div>
        ${{renderSubdirs(entry.subdirs)}}
    </div>`;
}}

// ── Main render ───────────────────────────────────────────────────────────────

function render() {{
    const contentEl = document.getElementById('content');
    const infoEl    = document.getElementById('search-info');
    const modeData  = data[`by_${{currentMode}}`];
    const q         = currentQuery;

    if (!modeData || Object.keys(modeData).length === 0) {{
        contentEl.innerHTML = emptyState('No data found');
        updateStats(0, 0);
        infoEl.style.display = 'none';
        return;
    }}

    let html = '';
    let totalShown = 0;
    let groupsShown = 0;

    for (const [key, entries] of Object.entries(modeData)) {{
        const matched = q ? entries.filter(e => entryMatches(e, q)) : entries;
        if (matched.length === 0) continue;

        groupsShown++;
        totalShown += matched.length;

        const countLabel = matched.length === entries.length
            ? `${{matched.length}} ${{matched.length === 1 ? 'entry' : 'entries'}}`
            : `${{matched.length}} / ${{entries.length}} entries`;

        html += `<div class="group">
            <div class="group-header">
                <span>${{groupIcon()}} ${{escHtml(key)}}</span>
                <span class="group-count">${{countLabel}}</span>
            </div>`;
        matched.forEach(e => {{ html += renderEntry(e, q); }});
        html += '</div>';
    }}

    contentEl.innerHTML = html || emptyState(`No results for "<strong>${{escHtml(q)}}</strong>"`);
    updateStats(totalShown, groupsShown);

    if (q) {{
        const total = Object.values(modeData).reduce((s,a) => s + a.length, 0);
        infoEl.style.display = 'block';
        infoEl.textContent = `Showing ${{totalShown}} of ${{total}} entries matching "${{q}}"`;
    }} else {{
        infoEl.style.display = 'none';
    }}
}}

function groupIcon() {{
    return {{ days:'📅', scenes:'🎞️', codes:'🏷️' }}[currentMode] || '📂';
}}
function updateStats(total, groups) {{
    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-groups').textContent = groups;
}}
function emptyState(msg) {{
    return `<div class="empty-state"><div class="empty-state-icon">📂</div><p>${{msg}}</p></div>`;
}}

render();
</script>
</body>
</html>"""


def main():
    import sys

    data_path   = "/Volumes/MACGUFF001/POSEIDON/DATA_rename"
    output_path = None

    if len(sys.argv) > 1:
        data_path = sys.argv[1]
    if len(sys.argv) > 2:
        output_path = sys.argv[2]

    print("\n" + "="*70)
    print("🎬 VFX SHOOT DATA HTML GENERATOR")
    print("="*70 + "\n")

    generator = HTMLGenerator(data_path)
    generator.parse_directories()
    generator.generate_html(output_path)

    print("\n✅ HTML page generated successfully!")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
