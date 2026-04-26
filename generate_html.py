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

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }}

        .container {{ max-width: 1400px; margin: 0 auto; }}

        header {{
            background: white;
            border-radius: 12px;
            padding: 24px 30px;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #1e3c72; font-size: 2.2em; margin-bottom: 6px; }}
        .subtitle {{ color: #666; font-size: 1em; }}

        /* ── Controls ── */
        .controls {{
            background: white;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 16px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }}

        .mode-button {{
            background: #f0f0f0;
            border: 2px solid #ddd;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 600;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        .mode-button:hover {{ background: #e0e0e0; transform: translateY(-1px); }}
        .mode-button.active {{ background: #1e3c72; color: white; border-color: #1e3c72; }}

        /* ── Search ── */
        .search-wrapper {{
            position: relative;
            flex: 1;
            min-width: 200px;
            max-width: 400px;
        }}
        .search-icon {{
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: #999;
            pointer-events: none;
        }}
        #search-input {{
            width: 100%;
            padding: 10px 36px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 0.95em;
            outline: none;
            transition: border-color 0.2s;
        }}
        #search-input:focus {{ border-color: #1e3c72; }}
        #search-clear {{
            position: absolute;
            right: 10px;
            top: 50%;
            transform: translateY(-50%);
            background: none;
            border: none;
            cursor: pointer;
            color: #aaa;
            font-size: 1.1em;
            display: none;
            line-height: 1;
        }}
        #search-clear:hover {{ color: #555; }}

        /* ── Stats ── */
        .stats {{ margin-left: auto; display: flex; gap: 20px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 1.6em; font-weight: bold; color: #1e3c72; }}
        .stat-label {{ font-size: 0.8em; color: #666; }}

        /* ── Search info ── */
        #search-info {{
            background: #e8f0fe;
            border-radius: 8px;
            padding: 8px 16px;
            margin-bottom: 12px;
            font-size: 0.9em;
            color: #1e3c72;
            display: none;
        }}

        /* ── Content ── */
        .content {{
            background: white;
            border-radius: 12px;
            padding: 28px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            min-height: 400px;
        }}

        .group {{ margin-bottom: 28px; }}
        .group-header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 13px 18px;
            border-radius: 8px;
            font-size: 1.2em;
            font-weight: bold;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .group-count {{
            background: rgba(255,255,255,0.2);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.78em;
        }}

        .entry {{
            background: #f8f9fa;
            border-left: 4px solid #1e3c72;
            padding: 16px 18px;
            margin-bottom: 12px;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .entry:hover {{
            background: #e9ecef;
            transform: translateX(4px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}

        /* ── Entry title line ── */
        .entry-title-line {{
            display: flex;
            align-items: baseline;
            gap: 7px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }}
        .title-day, .title-scene, .title-code, .title-desc {{
            display: inline-block;
            padding: 3px 9px;
            border-radius: 12px;
            font-weight: 700;
        }}
        .title-day   {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.85em;
            background: #d4edda;
            color: #155724;
        }}
        .title-scene {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.85em;
            background: #d1ecf1;
            color: #0c5460;
        }}
        .title-code  {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.85em;
            background: #fff3cd;
            color: #856404;
        }}
        .title-desc  {{
            font-size: 1.0em;
            background: #e8eaf6;
            color: #1e3c72;
        }}
        .badge-no-data {{
            background: #fd7e14;
            color: white;
            padding: 2px 9px;
            border-radius: 10px;
            font-size: 0.78em;
            font-weight: 600;
            align-self: center;
        }}

        mark {{
            background: #ffe066;
            color: inherit;
            border-radius: 2px;
            padding: 0 1px;
        }}

        /* ── Subdirectory sections ── */
        .subdir-sections {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #e0e0e0;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}

        /* nested: 20_HDR, 32_Photog_Photos, 40_Photos */
        .subdir-section-label {{
            font-size: 0.78em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #555;
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
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 0.82em;
            font-family: 'Monaco', 'Courier New', monospace;
        }}
        .subdir-child-count {{
            color: #888;
            font-size: 0.9em;
            margin-left: 12px;
            white-space: nowrap;
        }}

        /* count: 60_Temoin_Photos, 70_Temoin_Videos */
        .subdir-count-row {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.88em;
        }}
        .subdir-count-name {{
            font-weight: 600;
            color: #444;
        }}

        /* files: 10_Infos, 00_Database, 80_References */
        .subdir-file {{
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 3px 10px;
            font-size: 0.82em;
            font-family: 'Monaco', 'Courier New', monospace;
            color: #444;
        }}

        /* simple: other non-__ subdirs */
        .subdir-simple-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }}
        .subdir-simple-item {{
            background: white;
            border: 1px solid #ddd;
            padding: 3px 9px;
            border-radius: 6px;
            font-size: 0.82em;
            font-family: 'Monaco', 'Courier New', monospace;
            color: #555;
        }}

        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }}
        .empty-state-icon {{ font-size: 3.5em; margin-bottom: 16px; }}

        footer {{
            text-align: center;
            margin-top: 24px;
            color: white;
            opacity: 0.7;
            font-size: 0.85em;
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
        <h1>🎬 VFX Shoot Data Browser</h1>
        <p class="subtitle">Browse shoot data by days, scenes, or codes</p>
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
