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
    package_note: str = ''


class HTMLGenerator:

    DIR_PATTERN = re.compile(
        r'^(J\d{2}|PJ\d{2})__(S\d{2}(?:_S\d{2})*)__([A-Z]{4}(?:_[A-Z]{4})*)__(.+)$'
    )

    DEFAULT_SKIP_DIRS   = {'TODO__', '__RAPPORTS_SCRIPT', '__Souvenirs_Vrac', '__CALLSHEETS'}
    DEFAULT_TEMPLATE_DIR = 'J00_TEMPLATE'
    DEFAULT_HDR_SUBDIRS  = {'Fisheye': 'F', 'Theta': 'T', 'Theta_Underwater': 'U'}
    CONFIG_PATH          = '__SHOOT_BROWSER/Config/sanity_check.json'
    DELIVERY_CONFIG_PATH = '__SHOOT_BROWSER/Config/delivery_config.json'

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
        self.skip_dirs        = set(config.get('skip_dirs', self.DEFAULT_SKIP_DIRS))
        self.template_dir     = config.get('template_dir', self.DEFAULT_TEMPLATE_DIR)
        self.hdr_subdir_names = list(
            config.get('hdr_subdirs', self.DEFAULT_HDR_SUBDIRS).keys()
        )

        # Delivery config (separate file)
        delivery_cfg = {}
        dcfg_path = self.data_path / self.DELIVERY_CONFIG_PATH
        if dcfg_path.exists():
            try:
                with open(dcfg_path, 'r', encoding='utf-8') as f:
                    delivery_cfg = json.load(f)
            except Exception as e:
                print(f"⚠️  Could not load delivery config ({e}), using defaults")
        self.vendors             = delivery_cfg.get('vendors', [])
        self.default_output_dir  = delivery_cfg.get('default_output_dir', '')

    def default_output_path(self) -> Path:
        return self.data_path / '__SHOOT_BROWSER' / 'vfx_shoot_browser.html'

    # ── Block package note ───────────────────────────────────────────────────

    def _read_block_package_note(self, block_path: Path) -> str:
        """Read block_package_infos.txt from 10_Infos (or __10_Infos fallback)."""
        for prefix in ('', '__'):
            candidate = block_path / f'{prefix}10_Infos' / 'block_package_infos.txt'
            if candidate.is_file():
                try:
                    return candidate.read_text(encoding='utf-8').strip()
                except Exception:
                    pass
        return ''

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
                package_note=self._read_block_package_note(item),
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

    def build_data(self) -> dict:
        """Return the organised shoot data as a plain dict (JSON-serialisable)."""
        return {
            'by_days':   {k: [asdict(e) for e in v] for k, v in self.organize_by_days().items()},
            'by_scenes': {k: [asdict(e) for e in v] for k, v in self.organize_by_scenes().items()},
            'by_codes':  {k: [asdict(e) for e in v] for k, v in self.organize_by_codes().items()},
        }

    def generate_html(self, output_path: Optional[str] = None):
        print("🎨 Generating HTML page...")
        out = Path(output_path) if output_path else self.default_output_path()
        out.parent.mkdir(parents=True, exist_ok=True)

        with open(out, 'w', encoding='utf-8') as f:
            f.write(self._build_html(self.build_data()))

        print(f"   Saved to: {out}")

    def _build_html(self, data: dict) -> str:
        data_json      = json.dumps(data, indent=2)
        delivery_cfg_json = json.dumps({
            'vendors':            self.vendors,
            'default_output_dir': self.default_output_dir,
        })
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
        .open-folder, .toggle-btn {{
            background: none;
            border: none;
            cursor: pointer;
            color: var(--text-muted);
            opacity: 0.35;
            padding: 2px;
            line-height: 1;
            flex-shrink: 0;
            transition: opacity 0.15s, color 0.15s;
        }}
        .open-folder {{ margin-left: auto; }}
        .entry:hover .open-folder,
        .entry:hover .toggle-btn {{ opacity: 0.7; }}
        .open-folder:hover, .toggle-btn:hover {{ opacity: 1 !important; color: var(--accent); }}
        .open-folder.copied {{ opacity: 1 !important; color: #56d364; }}
        .toggle-btn svg {{ transition: transform 0.2s; }}
        .entry.expanded .toggle-btn {{ opacity: 0.7; }}
        .entry.expanded .toggle-btn svg {{ transform: rotate(180deg); }}

        /* ── Summary (collapsed) ── */
        .entry-summary {{
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 8px;
        }}
        .entry.expanded .entry-summary {{ display: none; }}
        .summary-subdir {{
            font-size: 0.75em;
            color: var(--text-muted);
            background: var(--surface-2);
            border: 1px solid var(--border);
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'Monaco', 'Courier New', monospace;
        }}

        /* ── Details (expanded) ── */
        .entry-details {{ display: none; }}
        .entry.expanded .entry-details {{ display: block; }}

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

        /* ── Cart ── */
        .entry-cb {{
            width: 16px; height: 16px; accent-color: var(--accent);
            cursor: pointer; flex-shrink: 0;
            opacity: 0; transition: opacity 0.15s; margin-right: 2px;
        }}
        .entry:hover .entry-cb, .entry.in-cart .entry-cb, .entry-cb:checked {{ opacity: 1; }}
        .entry.in-cart {{
            border-left-color: var(--accent) !important;
            background: rgba(68,147,248,0.1) !important;
        }}
        #cart-panel {{
            position: fixed; bottom: 0; left: 0; right: 0;
            background: var(--surface); border-top: 2px solid var(--accent);
            z-index: 100; display: none;
            box-shadow: 0 -6px 32px rgba(0,0,0,0.5);
        }}
        #cart-panel.visible {{ display: block; }}
        .cart-inner {{ max-width: 1400px; margin: 0 auto; }}
        #cart-header-bar {{
            display: flex; align-items: center; gap: 10px;
            padding: 10px 24px;
            border-bottom: 1px solid var(--border);
            cursor: default;
        }}
        .cart-title {{ font-weight: 700; color: var(--text); font-size: 0.9em; }}
        .cart-badge {{
            background: var(--accent); color: #fff;
            border-radius: 20px; padding: 1px 9px;
            font-size: 0.76em; font-weight: 700;
        }}
        .cart-toggle-btn {{
            background: none; border: none; cursor: pointer;
            color: var(--text-muted); font-size: 0.8em; padding: 2px 6px;
            transition: color 0.15s;
        }}
        .cart-toggle-btn:hover {{ color: var(--text); }}
        .cart-clear {{
            margin-left: auto; background: none;
            border: 1px solid var(--border); color: var(--text-muted);
            border-radius: 6px; padding: 3px 10px; cursor: pointer;
            font-size: 0.8em; transition: all 0.15s;
        }}
        .cart-clear:hover {{ color: #f85149; border-color: rgba(248,81,73,0.4); }}
        #cart-body {{
            max-height: 260px; overflow-y: auto;
            padding: 12px 24px 14px;
        }}
        #cart-panel.collapsed #cart-body {{ display: none; }}
        .cart-items {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }}
        .cart-item {{
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; padding: 8px 12px;
            display: flex; flex-direction: column; gap: 6px;
        }}
        .cart-item-top {{
            display: flex; align-items: center; gap: 8px;
        }}
        .cart-item-name {{
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.8em; color: var(--text);
            flex: 1; min-width: 0;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .cart-item-remove {{
            background: none; border: none; cursor: pointer;
            color: var(--text-muted); font-size: 0.9em;
            flex-shrink: 0; padding: 1px 4px; transition: color 0.15s;
        }}
        .cart-item-remove:hover {{ color: #f85149; }}
        .cart-item-note {{
            width: 100%; background: var(--surface-3);
            border: 1px solid var(--border); color: var(--text);
            border-radius: 4px; padding: 5px 8px;
            font-size: 0.82em; outline: none; transition: border-color 0.15s;
        }}
        .cart-item-note:focus {{ border-color: var(--accent); }}
        .cart-item-note::placeholder {{ color: var(--text-muted); }}
        .cart-collision {{
            background: rgba(248,81,73,0.1); border: 1px solid rgba(248,81,73,0.3);
            border-radius: 6px; padding: 8px 12px;
            font-size: 0.82em; color: #f85149; margin-bottom: 8px;
        }}
        .cart-package-note-row {{ margin-top: 8px; }}
        .cart-package-note-label {{
            display: block; font-size: 0.75em; font-weight: 600;
            color: var(--text-muted); text-transform: uppercase;
            letter-spacing: 0.06em; margin-bottom: 5px;
        }}
        .cart-package-note {{
            width: 100%; background: var(--surface-3);
            border: 1px solid var(--border); color: var(--text);
            border-radius: 6px; padding: 7px 10px;
            font-size: 0.85em; outline: none; transition: border-color 0.15s;
            resize: vertical; min-height: 52px; max-height: 120px;
            font-family: inherit;
        }}
        .cart-package-note:focus {{ border-color: var(--accent); }}
        .cart-package-note::placeholder {{ color: var(--text-muted); }}
        /* ── Build form ── */
        .cart-build-form {{
            margin-top: 12px; padding-top: 12px;
            border-top: 1px solid var(--border);
        }}
        .cart-build-title {{
            font-size: 0.75em; font-weight: 700; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px;
        }}
        .cart-form-row {{
            display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;
        }}
        .cart-form-field {{
            display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 140px;
        }}
        .cart-form-label {{
            font-size: 0.72em; color: var(--text-muted);
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .cart-form-input {{
            background: var(--surface-3); border: 1px solid var(--border);
            color: var(--text); border-radius: 4px; padding: 5px 8px;
            font-size: 0.85em; outline: none; transition: border-color 0.15s;
        }}
        .cart-form-input:focus {{ border-color: var(--accent); }}
        .cart-form-input::placeholder {{ color: var(--text-muted); }}
        .cart-build-btn {{
            background: var(--accent); color: #fff;
            border: none; border-radius: 6px; padding: 8px 20px;
            cursor: pointer; font-size: 0.88em; font-weight: 600;
            transition: opacity 0.15s; margin-top: 4px;
        }}
        .cart-build-btn:hover {{ opacity: 0.85; }}
        .cart-build-btn:disabled {{ opacity: 0.4; cursor: default; }}
        #build-status {{
            margin-top: 8px; padding: 8px 12px;
            border-radius: 6px; font-size: 0.82em; display: none;
            white-space: pre-wrap;
        }}
        #build-status.success {{
            background: rgba(86,211,100,0.12); border: 1px solid rgba(86,211,100,0.3);
            color: #56d364;
        }}
        #build-status.error {{
            background: rgba(248,81,73,0.1); border: 1px solid rgba(248,81,73,0.3);
            color: #f85149;
        }}
        /* ── Tab bar ── */
        .tab-bar {{
            display: flex; gap: 2px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 16px;
        }}
        .tab-btn {{
            background: none; border: none;
            border-bottom: 2px solid transparent;
            color: var(--text-muted); padding: 9px 18px;
            cursor: pointer; font-size: 0.88em; font-weight: 600;
            margin-bottom: -1px; transition: all 0.15s;
        }}
        .tab-btn:hover {{ color: var(--text); }}
        .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
        .tab-badge {{
            background: var(--accent); color: #fff;
            border-radius: 20px; padding: 1px 7px;
            font-size: 0.74em; font-weight: 700;
            margin-left: 5px; vertical-align: middle;
        }}

        /* ── Queue view ── */
        .queue-toolbar {{
            display: flex; align-items: center; gap: 10px;
            margin-bottom: 12px; flex-wrap: wrap;
        }}
        .queue-build-btn {{
            background: var(--accent); color: #fff;
            border: none; border-radius: 6px; padding: 8px 18px;
            cursor: pointer; font-size: 0.88em; font-weight: 600;
            transition: opacity 0.15s;
        }}
        .queue-build-btn:hover {{ opacity: 0.85; }}
        .queue-build-btn:disabled {{ opacity: 0.4; cursor: default; }}
        .queue-select-all {{
            background: none; border: 1px solid var(--border);
            color: var(--text-muted); border-radius: 6px;
            padding: 6px 14px; cursor: pointer; font-size: 0.82em;
            transition: all 0.15s;
        }}
        .queue-select-all:hover {{ color: var(--text); border-color: var(--border-hover); }}
        .queue-count-label {{ color: var(--text-muted); font-size: 0.85em; margin-left: auto; }}
        .queue-item {{
            background: var(--surface); border: 1px solid var(--border);
            border-left: 3px solid transparent;
            border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
            display: flex; align-items: center; gap: 12px; transition: all 0.15s;
        }}
        .queue-item:hover {{
            border-color: var(--border-hover); border-left-color: var(--accent);
            background: var(--surface-2);
        }}
        .queue-item.selected {{ border-left-color: var(--accent); }}
        .queue-cb {{ width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0; }}
        .queue-item-info {{ flex: 1; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
        .queue-vendor {{
            background: rgba(86,211,100,0.12); color: #56d364;
            border: 1px solid rgba(86,211,100,0.2);
            padding: 2px 9px; border-radius: 6px;
            font-size: 0.8em; font-weight: 600; font-family: 'Monaco','Courier New',monospace;
        }}
        .queue-name {{
            background: rgba(68,147,248,0.12); color: #7eb8f7;
            border: 1px solid rgba(68,147,248,0.2);
            padding: 2px 9px; border-radius: 6px;
            font-size: 0.8em; font-weight: 600; font-family: 'Monaco','Courier New',monospace;
        }}
        .queue-date {{
            background: rgba(227,179,65,0.12); color: #e3b341;
            border: 1px solid rgba(227,179,65,0.2);
            padding: 2px 9px; border-radius: 6px;
            font-size: 0.8em; font-weight: 600; font-family: 'Monaco','Courier New',monospace;
        }}
        .queue-meta {{ color: var(--text-muted); font-size: 0.8em; }}
        .queue-item-actions {{ display: flex; gap: 6px; flex-shrink: 0; }}
        .queue-edit-btn, .queue-delete-btn {{
            background: none; border: 1px solid var(--border);
            border-radius: 5px; padding: 3px 10px;
            cursor: pointer; font-size: 0.8em; transition: all 0.15s;
        }}
        .queue-edit-btn {{ color: var(--accent); }}
        .queue-edit-btn:hover {{ background: var(--accent-glow); border-color: var(--accent); }}
        .queue-delete-btn {{ color: var(--text-muted); }}
        .queue-delete-btn:hover {{ color: #f85149; border-color: rgba(248,81,73,0.4); }}
        #build-progress {{
            margin-top: 12px; padding: 10px 14px; border-radius: 6px;
            font-size: 0.85em; display: none; white-space: pre-wrap;
        }}
        #build-progress.running {{
            background: var(--accent-glow); border: 1px solid rgba(68,147,248,0.3); color: var(--accent);
        }}
        #build-progress.done-ok {{
            background: rgba(86,211,100,0.1); border: 1px solid rgba(86,211,100,0.3); color: #56d364;
        }}
        #build-progress.done-err {{
            background: rgba(248,81,73,0.1); border: 1px solid rgba(248,81,73,0.3); color: #f85149;
        }}
        /* ── Delivered theme ── */
        .delivered-active {{
            --accent:      #4ac26b;
            --accent-glow: rgba(74,194,107,0.15);
        }}
        .delivered-active .tab-btn.active {{
            color: #4ac26b; border-bottom-color: #4ac26b;
        }}

        /* ── Delivered view controls ── */
        #del-search-input {{
            width: 100%; padding: 8px 34px;
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; color: var(--text); font-size: 0.9em;
            outline: none; transition: border-color 0.15s;
        }}
        #del-search-input::placeholder {{ color: var(--text-muted); }}
        #del-search-input:focus {{ border-color: var(--accent); }}
        #del-search-clear {{
            position: absolute; right: 9px; top: 50%; transform: translateY(-50%);
            background: none; border: none; cursor: pointer;
            color: var(--text-muted); font-size: 1em; display: none; line-height: 1;
        }}
        #del-search-clear:hover {{ color: var(--text); }}

        /* ── Delivered package cards ── */
        .del-entry {{
            background: var(--surface); border: 1px solid var(--border);
            border-left: 3px solid transparent;
            padding: 12px 16px; margin-bottom: 8px;
            border-radius: 8px; transition: all 0.15s;
        }}
        .del-entry:hover {{
            background: var(--surface-2); border-color: var(--border-hover);
            border-left-color: var(--accent); transform: translateX(3px);
        }}
        .del-vendor-badge {{
            background: rgba(74,194,107,0.12); color: #4ac26b;
            border: 1px solid rgba(74,194,107,0.25);
            padding: 3px 9px; border-radius: 6px;
            font-size: 0.8em; font-weight: 700;
            font-family: 'Monaco','Courier New',monospace;
        }}
        .del-name-badge {{
            background: rgba(68,147,248,0.12); color: #7eb8f7;
            border: 1px solid rgba(68,147,248,0.2);
            padding: 3px 9px; border-radius: 6px;
            font-size: 0.88em; font-weight: 600;
        }}
        .del-date-badge {{
            background: rgba(227,179,65,0.12); color: #e3b341;
            border: 1px solid rgba(227,179,65,0.2);
            padding: 3px 9px; border-radius: 6px;
            font-size: 0.8em; font-weight: 600;
            font-family: 'Monaco','Courier New',monospace;
        }}
        .del-version {{
            background: rgba(163,113,247,0.12); color: #a371f7;
            border: 1px solid rgba(163,113,247,0.2);
            padding: 2px 8px; border-radius: 6px;
            font-size: 0.76em; font-weight: 700;
        }}
        .del-blocks {{
            margin-top: 8px; padding-top: 8px;
            border-top: 1px solid var(--border);
            display: flex; flex-direction: column; gap: 4px;
        }}
        .del-block-row {{
            display: flex; align-items: center; gap: 5px; flex-wrap: wrap;
        }}
        .del-block-name {{
            font-family: 'Monaco','Courier New',monospace;
            font-size: 0.78em; color: var(--text-muted);
            margin-right: 4px;
        }}
        .del-block-note {{
            font-size: 0.76em; color: var(--text-muted);
            font-style: italic; margin-left: 4px;
        }}
        .del-pkg-note {{
            margin-top: 6px; font-size: 0.82em;
            color: var(--text-muted); font-style: italic;
        }}
        .database-active {{
            --accent: #a371f7;
            --accent-glow: rgba(163,113,247,0.15);
        }}
        .database-active .tab-btn.active {{
            color: #a371f7; border-bottom-color: #a371f7;
        }}
        .database-active .entry:not(.expanded) {{
            padding: 7px 14px;
        }}
        .database-active .entry:not(.expanded) .entry-title-line {{
            margin-bottom: 0;
        }}
        .db-filter-row {{
            display: flex; flex-wrap: wrap; gap: 8px 12px;
            margin-top: 12px; align-items: flex-end;
        }}
        .db-filter-field {{
            display: flex; flex-direction: column; gap: 3px;
        }}
        .db-filter-field label {{
            font-size: 0.7em; color: var(--text-muted); font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .db-filter-input {{
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; color: var(--text); font-size: 0.82em;
            padding: 5px 8px; width: 90px; transition: border-color 0.15s;
        }}
        .db-filter-input:focus {{ outline: none; border-color: var(--accent); }}
        .db-filter-input::placeholder {{ color: var(--text-muted); }}
        .db-sort-select {{
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; color: var(--text); font-size: 0.82em;
            padding: 5px 8px; cursor: pointer;
        }}
        .db-sort-dir {{
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; color: var(--text); font-size: 0.9em;
            padding: 5px 10px; cursor: pointer; transition: all 0.15s; line-height: 1;
        }}
        .db-sort-dir:hover {{ border-color: var(--accent); color: var(--accent); }}
        .db-slate {{
            font-family: 'Monaco','Courier New',monospace; font-size: 0.85em; font-weight: 700;
            background: rgba(163,113,247,0.12); color: #a371f7;
            border: 1px solid rgba(163,113,247,0.2); padding: 2px 9px; border-radius: 6px;
        }}
        .db-vfxid {{
            font-family: 'Monaco','Courier New',monospace; font-size: 0.78em;
            background: rgba(57,197,207,0.10); color: #39c5cf;
            border: 1px solid rgba(57,197,207,0.2); padding: 2px 8px; border-radius: 6px;
        }}
        .db-date {{
            font-family: 'Monaco','Courier New',monospace; font-size: 0.78em;
            background: rgba(227,179,65,0.10); color: #e3b341;
            border: 1px solid rgba(227,179,65,0.2); padding: 2px 8px; border-radius: 6px;
        }}
        .db-day {{
            font-family: 'Monaco','Courier New',monospace; font-size: 0.78em;
            background: rgba(86,211,100,0.10); color: #56d364;
            border: 1px solid rgba(86,211,100,0.2); padding: 2px 8px; border-radius: 6px;
        }}
        .db-roll {{
            font-family: 'Monaco','Courier New',monospace; font-size: 0.75em;
            color: var(--text-muted); background: var(--surface-2);
            border: 1px solid var(--border); padding: 2px 8px; border-radius: 6px;
        }}
        .db-lens, .db-focal, .db-tilt {{
            font-size: 0.78em; color: #f78166;
            background: rgba(247,129,102,0.10);
            border: 1px solid rgba(247,129,102,0.2); padding: 2px 8px; border-radius: 6px;
        }}
        .db-details {{ display: flex; flex-direction: column; gap: 16px; }}
        .db-section {{ display: flex; flex-direction: column; gap: 2px; }}
        .db-section-label {{
            font-size: 0.7em; letter-spacing: 0.06em;
            color: var(--accent); font-weight: 700;
            border-bottom: 1px solid var(--border); padding-bottom: 2px;
        }}
        .db-row {{ display: flex; flex-wrap: wrap; gap: 4px 18px; align-items: baseline; }}
        .db-field {{ display: flex; gap: 5px; align-items: baseline; font-size: 0.8em; }}
        .db-field-label {{ color: var(--text-muted); font-size: 0.88em; white-space: nowrap; }}
        .db-field-value {{ color: var(--text); font-weight: 500; }}
        .db-field-value.empty {{ color: var(--text-muted); font-style: italic; }}
        .db-tag {{
            display: inline-block; font-size: 0.78em;
            background: rgba(205,217,229,0.12); color: #cdd9e5;
            border: 1px solid rgba(205,217,229,0.22);
            padding: 2px 9px; border-radius: 4px; margin: 1px 2px;
        }}
        .extract-slates-btn {{
            background: var(--surface-2); border: 1px solid var(--border);
            border-radius: 6px; color: var(--text-muted); cursor: pointer;
            font-size: 0.82em; padding: 6px 12px; transition: all 0.15s; white-space: nowrap;
        }}
        .extract-slates-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
        .extract-slates-btn:disabled {{ opacity: 0.5; cursor: default; }}
        .extract-slates-btn.needs-refresh {{
            border-color: rgba(227,179,65,0.5); color: #e3b341;
            background: rgba(227,179,65,0.08);
        }}
        .extract-status {{ font-size: 0.78em; color: var(--text-muted); }}
        .extract-status.ok  {{ color: #56d364; }}
        .extract-status.err {{ color: #f85149; }}
        body.cart-open {{ padding-bottom: 370px; }}
        body.cart-open.cart-collapsed {{ padding-bottom: 48px; }}
    </style>
</head>
<body>
<div class="container">

    <header>
        <h1>VFX Shoot Browser</h1>
        <p class="subtitle">POSEIDON — Browse shoot data by days, scenes, or codes</p>
    </header>

    <nav class="tab-bar">
      <button class="tab-btn active" onclick="setView('browse')" id="tab-browse">📂 Browse</button>
      <button class="tab-btn" onclick="setView('database')" id="tab-database">🗄️ Database</button>
      <button class="tab-btn" onclick="setView('queue')" id="tab-queue">📋 Queue</button>
      <button class="tab-btn" onclick="setView('delivered')" id="tab-delivered">✅ Delivered</button>
    </nav>

    <div id="view-browse">
    <div class="controls">
        <button class="mode-button active" onclick="setMode('days')"   id="btn-days">📅 By Days</button>
        <button class="mode-button"        onclick="setMode('scenes')" id="btn-scenes">🎞️ By Scenes</button>
        <button class="mode-button"        onclick="setMode('codes')"  id="btn-codes">🏷️ By Codes</button>
        <button class="mode-button"        onclick="toggleAll()"       id="btn-toggle-all">⊕ Expand All</button>
        <button class="extract-slates-btn" id="extract-slates-btn"   onclick="runExtractSlates()">📊 Extract Slates</button>
        <span id="extract-status" class="extract-status"></span>

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

    </div><!-- end view-browse -->

    <div id="view-database" style="display:none">
      <div class="controls">
        <button class="mode-button active" onclick="setDbGroup('scene')"     id="db-grp-scene">🎬 Scene</button>
        <button class="mode-button"        onclick="setDbGroup('vfx_id')"    id="db-grp-vfx_id">🎭 VFX ID</button>
        <button class="mode-button"        onclick="setDbGroup('date')"      id="db-grp-date">📅 Date</button>
        <button class="mode-button"        onclick="setDbGroup('shoot_day')" id="db-grp-shoot_day">🎬 Shoot Day</button>
        <button class="mode-button"        onclick="setDbGroup('lens')"      id="db-grp-lens">🔭 Lens</button>
        <button class="mode-button"        onclick="setDbGroup('focal')"     id="db-grp-focal">📐 Focal</button>
        <select id="db-sort-select" class="db-sort-select" onchange="setDbSort(this.value)">
          <option value="scene">Sort: Scene</option>
          <option value="slate">Sort: Slate</option>
          <option value="vfx_id">Sort: VFX ID</option>
          <option value="date">Sort: Date</option>
          <option value="shoot_day">Sort: Shoot Day</option>
          <option value="lens">Sort: Lens</option>
          <option value="focal">Sort: Focal</option>
        </select>
        <button id="db-sort-dir" class="db-sort-dir" onclick="toggleDbSortDir()" title="Toggle sort direction">↑</button>
      </div>
      <div class="db-filter-row">
        <div class="db-filter-field">
          <label>Slate</label>
          <input class="db-filter-input" type="text" id="dbf-slate"
                 oninput="setDbFilter('slate', this.value)" placeholder="49A">
        </div>
        <div class="db-filter-field">
          <label>VFX ID</label>
          <input class="db-filter-input" type="text" id="dbf-vfx_id"
                 oninput="setDbFilter('vfx_id', this.value)" placeholder="">
        </div>
        <div class="db-filter-field">
          <label>Date</label>
          <input class="db-filter-input" type="text" id="dbf-date"
                 oninput="setDbFilter('date', this.value)" placeholder="2026-04">
        </div>
        <div class="db-filter-field">
          <label>Shoot Day</label>
          <input class="db-filter-input" type="text" id="dbf-shoot_day"
                 oninput="setDbFilter('shoot_day', this.value)" placeholder="2">
        </div>
        <div class="db-filter-field">
          <label>Roll</label>
          <input class="db-filter-input" type="text" id="dbf-roll"
                 oninput="setDbFilter('roll', this.value)" placeholder="">
        </div>
        <div class="db-filter-field">
          <label>Lens</label>
          <input class="db-filter-input" type="text" id="dbf-lens"
                 oninput="setDbFilter('lens', this.value)" placeholder="35mm">
        </div>
        <div class="db-filter-field">
          <label>Focal</label>
          <input class="db-filter-input" type="text" id="dbf-focal"
                 oninput="setDbFilter('focal', this.value)" placeholder="35mm">
        </div>
        <div class="search-wrapper" style="flex:1;min-width:180px">
          <span class="search-icon">🔍</span>
          <input id="db-global-search" type="text"
                 placeholder="Search all other fields…"
                 oninput="setDbQuery(this.value)">
          <button id="db-search-clear" onclick="clearDbSearch()" title="Clear">✕</button>
        </div>
      </div>
      <div id="database-content" style="margin-top:16px"></div>
    </div>

    <div id="view-queue" style="display:none">
      <div class="queue-toolbar">
        <button class="queue-build-btn" id="queue-build-btn" onclick="buildSelected()">🏗️ Build selected</button>
        <button class="queue-select-all" onclick="toggleSelectAll()">Select all</button>
        <span class="queue-count-label" id="queue-count-label"></span>
      </div>
      <div id="queue-list"></div>
      <div id="build-progress"></div>
    </div>

    <div id="view-delivered" style="display:none">
      <div class="controls">
        <button class="mode-button active" onclick="setDeliveredMode('vendor')"  id="del-btn-vendor">🏢 By Vendor</button>
        <button class="mode-button"        onclick="setDeliveredMode('date')"    id="del-btn-date">📅 By Date</button>
        <button class="mode-button"        onclick="setDeliveredMode('scene')"   id="del-btn-scene">🎞️ By Scene</button>
        <button class="mode-button"        onclick="setDeliveredMode('code')"    id="del-btn-code">🏷️ By Code</button>
        <div class="search-wrapper">
          <span class="search-icon">🔍</span>
          <input id="del-search-input" type="text"
                 placeholder="Search vendor, package, block…"
                 oninput="onDeliveredSearch(this.value)">
          <button id="del-search-clear" onclick="clearDeliveredSearch()" title="Clear">✕</button>
        </div>
      </div>
      <div id="delivered-content"></div>
    </div>

    <footer>Generated on {generated_time}</footer>

</div>

<div id="cart-panel">
  <div class="cart-inner">
    <div id="cart-header-bar">
      <span class="cart-title">📦 Delivery Cart</span>
      <span class="cart-badge" id="cart-count">0</span>
      <button class="cart-toggle-btn" id="cart-toggle-btn" onclick="toggleCartCollapse()" title="Collapse / Expand">▲</button>
      <button class="cart-clear" onclick="clearCart()">Clear all</button>
    </div>
    <div id="cart-body">
      <div id="cart-items" class="cart-items"></div>
      <div id="cart-collisions"></div>
      <div class="cart-package-note-row">
        <label class="cart-package-note-label" for="package-note-input">Package note</label>
        <textarea id="package-note-input" class="cart-package-note"
          placeholder="Optional — written to Package_Infos.txt at the delivery root"
          oninput="savePackageNote(this.value)"></textarea>
      </div>
      <div class="cart-build-form">
        <div class="cart-build-title">Build Package</div>
        <div class="cart-form-row">
          <div class="cart-form-field">
            <label class="cart-form-label">Vendor</label>
            <select id="pkg-vendor-select" class="cart-form-input" onchange="onVendorChange(this)"></select>
            <input id="pkg-vendor-custom" class="cart-form-input" type="text"
              placeholder="Enter vendor name…" style="display:none;margin-top:4px">
          </div>
          <div class="cart-form-field">
            <label class="cart-form-label" for="pkg-name">Package name</label>
            <input id="pkg-name" class="cart-form-input" type="text" placeholder="poseidon_HDR_batch01">
          </div>
          <div class="cart-form-field" style="max-width:160px">
            <label class="cart-form-label" for="pkg-date">Date</label>
            <input id="pkg-date" class="cart-form-input" type="date">
          </div>
        </div>
        <div class="cart-form-row">
          <div class="cart-form-field">
            <label class="cart-form-label" for="pkg-output-dir">Output directory</label>
            <input id="pkg-output-dir" class="cart-form-input" type="text" placeholder="/path/to/delivery">
          </div>
        </div>
        <button class="cart-build-btn" id="build-btn" onclick="saveToQueue()">+ Save to Queue</button>
        <div id="build-status"></div>
      </div>
    </div>
  </div>
</div>

<script>
const data           = {data_json};
const deliveryCfg    = {delivery_cfg_json};

// Flat index: path → entry object (for cart lookups)
const allEntries = {{}};
for (const view of Object.values(data)) {{
    for (const arr of Object.values(view)) {{
        for (const e of arr) {{ allEntries[e.path] = e; }}
    }}
}}

let currentMode  = 'days';
let currentQuery = '';
const expandedPaths = new Set();

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

function renderSummary(subdirs) {{
    if (!subdirs || subdirs.length === 0) return '';
    const pills = [];
    for (const s of subdirs) {{
        if (s.kind === 'simple') {{
            s.children.forEach(c => pills.push(`<span class="summary-subdir">${{escHtml(c.name)}}</span>`));
        }} else {{
            pills.push(`<span class="summary-subdir">📁 ${{escHtml(s.name)}}</span>`);
        }}
    }}
    return pills.length ? `<div class="entry-summary">${{pills.join('')}}</div>` : '';
}}

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
    const copyBtn    = `<button class="open-folder" onclick="copyPath(this, this.closest('.entry').dataset.path)" title="Copy path (then ⌘⇧G in Finder)">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg></button>`;
    const chevron    = `<button class="toggle-btn" onclick="toggleEntry(this)" title="Expand / Collapse">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"/>
        </svg></button>`;

    const inCart     = cart.has(entry.path);
    const cb         = `<input type="checkbox" class="entry-cb" ${{inCart ? 'checked' : ''}} onclick="toggleCart(this.closest('.entry').dataset.path)">`;
    const isExpanded = expandedPaths.has(entry.path);
    return `<div class="entry${{inCart ? ' in-cart' : ''}}${{isExpanded ? ' expanded' : ''}}" data-path="${{escHtml(entry.path)}}">
        <div class="entry-title-line">
            ${{cb}}${{dayHtml}}${{scenesHtml}}${{codesHtml}}${{descHtml}}${{noData}}${{copyBtn}}${{chevron}}
        </div>
        ${{renderSummary(entry.subdirs)}}
        <div class="entry-details">${{renderSubdirs(entry.subdirs)}}</div>
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

// ── Fold / unfold ────────────────────────────────────────────────────────────

function toggleEntry(btn) {{
    const entry = btn.closest('.entry');
    const path  = entry.dataset.path;
    const expanded = entry.classList.toggle('expanded');
    if (expanded) expandedPaths.add(path);
    else           expandedPaths.delete(path);
}}

function toggleAll() {{
    const entries     = document.querySelectorAll('.entry[data-path]');
    const anyCollapsed = [...entries].some(e => !e.classList.contains('expanded'));
    entries.forEach(e => {{
        e.classList.toggle('expanded', anyCollapsed);
        if (anyCollapsed) expandedPaths.add(e.dataset.path);
        else              expandedPaths.delete(e.dataset.path);
    }});
    const btn = document.getElementById('btn-toggle-all');
    if (btn) btn.textContent = anyCollapsed ? '⊖ Collapse All' : '⊕ Expand All';
}}

// ── Copy path ────────────────────────────────────────────────────────────────

function copyPath(btn, path) {{
    const ta = document.createElement('textarea');
    ta.value = path;
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);

    if (ok) {{
        const orig = btn.innerHTML;
        btn.classList.add('copied');
        btn.innerHTML = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
        setTimeout(() => {{
            btn.classList.remove('copied');
            btn.innerHTML = orig;
        }}, 1500);
    }} else {{
        window.prompt('Copy path:', path);
    }}
}}

// ── Cart ─────────────────────────────────────────────────────────────────────

const CART_KEY    = 'vfx_shoot_cart';
const PKG_NOTE_KEY = 'vfx_shoot_pkg_note';
const cart = new Map(); // path → {{entry, note}}

function deliveryName(entry) {{
    return entry.scenes.join('_') + '__' + entry.code + '__' + entry.description;
}}

function cartSave() {{
    const arr = [...cart.entries()].map(([p, {{note}}]) => ({{ path: p, note }}));
    localStorage.setItem(CART_KEY, JSON.stringify(arr));
}}

function cartLoad() {{
    try {{
        const saved = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
        saved.forEach(({{ path, note }}) => {{
            if (allEntries[path]) cart.set(path, {{ entry: allEntries[path], note }});
        }});
    }} catch(e) {{}}
}}

function savePackageNote(value) {{
    localStorage.setItem(PKG_NOTE_KEY, value);
}}

function loadPackageNote() {{
    const el = document.getElementById('package-note-input');
    if (el) el.value = localStorage.getItem(PKG_NOTE_KEY) || '';
}}

function toggleCartCollapse() {{
    const panel = document.getElementById('cart-panel');
    const btn   = document.getElementById('cart-toggle-btn');
    const collapsed = panel.classList.toggle('collapsed');
    document.body.classList.toggle('cart-collapsed', collapsed);
    btn.textContent = collapsed ? '▼' : '▲';
}}

function cartCollisions() {{
    const nameMap = new Map();
    for (const [path, {{ entry }}] of cart) {{
        const dn = deliveryName(entry);
        if (!nameMap.has(dn)) nameMap.set(dn, []);
        nameMap.get(dn).push(entry.directory_name);
    }}
    return [...nameMap.entries()]
        .filter(([, names]) => names.length > 1)
        .map(([dn, names]) => ({{ dn, names }}));
}}

function toggleCart(path) {{
    if (cart.has(path)) {{
        cart.delete(path);
    }} else {{
        const entry = allEntries[path];
        if (entry) cart.set(path, {{ entry, note: entry.package_note || '' }});
    }}
    cartSave();
    syncEntryEl(path);
    renderCart();
}}

function removeFromCart(path) {{
    cart.delete(path);
    cartSave();
    syncEntryEl(path);
    renderCart();
}}

function clearCart() {{
    cart.clear();
    cartSave();
    document.querySelectorAll('.entry').forEach(el => {{
        el.classList.remove('in-cart');
        const cb = el.querySelector('.entry-cb');
        if (cb) cb.checked = false;
    }});
    renderCart();
}}

function updateCartNote(path, note) {{
    if (cart.has(path)) {{ cart.get(path).note = note; cartSave(); }}
}}

function syncEntryEl(path) {{
    document.querySelectorAll('.entry').forEach(el => {{
        if (el.dataset.path !== path) return;
        const inCart = cart.has(path);
        el.classList.toggle('in-cart', inCart);
        const cb = el.querySelector('.entry-cb');
        if (cb) cb.checked = inCart;
    }});
}}

function renderCart() {{
    const panel   = document.getElementById('cart-panel');
    const countEl = document.getElementById('cart-count');
    const itemsEl = document.getElementById('cart-items');
    const colEl   = document.getElementById('cart-collisions');

    if (cart.size === 0) {{
        panel.classList.remove('visible');
        document.body.classList.remove('cart-open', 'cart-collapsed');
        return;
    }}

    panel.classList.add('visible');
    document.body.classList.add('cart-open');
    countEl.textContent = cart.size;

    itemsEl.innerHTML = [...cart.entries()].map(([path, {{ entry, note }}]) => {{
        const dn   = escHtml(deliveryName(entry));
        const orig = escHtml(entry.directory_name);
        const n    = escHtml(note);
        return `<div class="cart-item" data-path="${{escHtml(path)}}">
            <div class="cart-item-top">
                <span class="cart-item-name" title="${{orig}}">${{dn}}</span>
                <button class="cart-item-remove"
                    onclick="removeFromCart(this.closest('.cart-item').dataset.path)"
                    title="Remove">✕</button>
            </div>
            <input class="cart-item-note" type="text" placeholder="Block note (optional)"
                   value="${{n}}"
                   oninput="updateCartNote(this.closest('.cart-item').dataset.path, this.value)">
        </div>`;
    }}).join('');

    const cols = cartCollisions();
    colEl.innerHTML = cols.map(({{ dn, names }}) =>
        `<div class="cart-collision">⚠️ Delivery name collision: <strong>${{escHtml(dn)}}</strong><br>${{names.map(n => '· ' + escHtml(n)).join('<br>')}}</div>`
    ).join('');
}}

// ── Package builder form ──────────────────────────────────────────────────────

const BUILD_FORM_KEY = 'vfx_build_form';

function initVendorSelect() {{
    const sel     = document.getElementById('pkg-vendor-select');
    const vendors = deliveryCfg.vendors || [];
    sel.innerHTML = '';
    if (vendors.length === 0) {{
        sel.style.display = 'none';
        document.getElementById('pkg-vendor-custom').style.display = 'block';
        return;
    }}
    vendors.forEach(v => {{
        const o = document.createElement('option'); o.value = v; o.textContent = v;
        sel.appendChild(o);
    }});
    const customOpt = document.createElement('option');
    customOpt.value = '__custom__'; customOpt.textContent = 'Custom…';
    sel.appendChild(customOpt);
}}

function onVendorChange(sel) {{
    document.getElementById('pkg-vendor-custom').style.display =
        sel.value === '__custom__' ? 'block' : 'none';
}}

function getVendor() {{
    const sel = document.getElementById('pkg-vendor-select');
    if (sel.style.display === 'none' || sel.value === '__custom__')
        return document.getElementById('pkg-vendor-custom').value.trim();
    return sel.value;
}}

function loadBuildForm() {{
    initVendorSelect();
    document.getElementById('pkg-date').value = new Date().toISOString().split('T')[0];
    try {{
        const saved = JSON.parse(localStorage.getItem(BUILD_FORM_KEY) || '{{}}');
        // Restore vendor
        const savedVendor = saved['pkg-vendor'] || '';
        const vendors = deliveryCfg.vendors || [];
        const sel = document.getElementById('pkg-vendor-select');
        if (savedVendor && vendors.includes(savedVendor) && sel.style.display !== 'none') {{
            sel.value = savedVendor;
        }} else if (savedVendor && sel.style.display !== 'none') {{
            sel.value = '__custom__';
            const customEl = document.getElementById('pkg-vendor-custom');
            customEl.style.display = 'block';
            customEl.value = savedVendor;
        }} else if (savedVendor) {{
            document.getElementById('pkg-vendor-custom').value = savedVendor;
        }}
        // Restore package name
        const nameEl = document.getElementById('pkg-name');
        if (nameEl && saved['pkg-name']) nameEl.value = saved['pkg-name'];
        // Restore output dir (saved value takes priority over config default)
        const dirEl = document.getElementById('pkg-output-dir');
        if (dirEl) dirEl.value = saved['pkg-output-dir'] || deliveryCfg.default_output_dir || '';
    }} catch(e) {{
        // Fall back to config default for output dir
        const dirEl = document.getElementById('pkg-output-dir');
        if (dirEl) dirEl.value = deliveryCfg.default_output_dir || '';
    }}
}}

function saveBuildForm() {{
    const saved = {{
        'pkg-vendor':     getVendor(),
        'pkg-name':       (document.getElementById('pkg-name') || {{}}).value || '',
        'pkg-output-dir': (document.getElementById('pkg-output-dir') || {{}}).value || '',
    }};
    localStorage.setItem(BUILD_FORM_KEY, JSON.stringify(saved));
}}

function showBuildStatus(type, msg) {{
    const el = document.getElementById('build-status');
    if (!type) {{ el.style.display = 'none'; return; }}
    el.className = type;
    el.style.display = 'block';
    el.textContent = msg;
}}

function saveToQueue() {{
    const vendor    = getVendor();
    const pkgName   = document.getElementById('pkg-name').value.trim();
    const date      = document.getElementById('pkg-date').value;
    const outputDir = document.getElementById('pkg-output-dir').value.trim();
    const pkgNote   = document.getElementById('package-note-input').value.trim();

    if (!vendor || !pkgName || !outputDir) {{
        showBuildStatus('error', 'Vendor, Package name and Output directory are required.');
        return;
    }}
    if (cart.size === 0) {{
        showBuildStatus('error', 'No blocks in cart.');
        return;
    }}

    const pkg = {{
        id:           Date.now(),
        vendor,
        package_name: pkgName,
        date,
        output_dir:   outputDir,
        package_note: pkgNote,
        blocks: [...cart.entries()].map(([path, {{ entry, note }}]) => ({{
            path,
            delivery_name: deliveryName(entry),
            scenes:        entry.scenes,
            code:          entry.code,
            description:   entry.description,
            note,
        }})),
    }};

    const queue = loadQueue();
    queue.push(pkg);
    saveQueue(queue);
    saveBuildForm();

    clearCart();
    document.getElementById('pkg-name').value           = '';
    document.getElementById('package-note-input').value = '';
    savePackageNote('');

    showBuildStatus('success',
        `✓ "${{pkgName}}" added to queue. ${{queue.length}} package${{queue.length === 1 ? '' : 's'}} pending.`);
}}

// ── Queue ─────────────────────────────────────────────────────────────────────

const QUEUE_KEY = 'vfx_pending_packages';

function loadQueue() {{
    try {{ return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); }}
    catch(e) {{ return []; }}
}}

function saveQueue(queue) {{
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
    updateQueueBadge();
}}

function updateQueueBadge() {{
    const n   = loadQueue().length;
    const tab = document.getElementById('tab-queue');
    if (!tab) return;
    tab.innerHTML = n
        ? `📋 Queue <span class="tab-badge">${{n}}</span>`
        : '📋 Queue';
}}

function setView(view) {{
    ['browse', 'database', 'queue', 'delivered'].forEach(v => {{
        document.getElementById(`view-${{v}}`).style.display = v === view ? 'block' : 'none';
        document.getElementById(`tab-${{v}}`).classList.toggle('active', v === view);
    }});
    const container = document.querySelector('.container');
    container.classList.toggle('delivered-active', view === 'delivered');
    container.classList.toggle('database-active',  view === 'database');
    if (view === 'delivered') loadDelivered();
    if (view === 'database')  loadDatabase();
    if (view === 'queue')     renderQueue();
}}

// ── Delivered packages view ───────────────────────────────────────────────────
let deliveredMode      = 'vendor';
let deliveredQuery     = '';
let deliveredPackages  = [];
const expandedDelBlocks = new Set();

function setDeliveredMode(mode) {{
    deliveredMode = mode;
    ['vendor','date','scene','code'].forEach(m => {{
        document.getElementById(`del-btn-${{m}}`).classList.toggle('active', m === mode);
    }});
    renderDelivered();
}}

function onDeliveredSearch(val) {{
    deliveredQuery = val.trim().toLowerCase();
    document.getElementById('del-search-clear').style.display = val ? 'flex' : 'none';
    renderDelivered();
}}

function clearDeliveredSearch() {{
    const el = document.getElementById('del-search-input');
    if (el) el.value = '';
    onDeliveredSearch('');
}}

function pkgMatches(pkg, q) {{
    if (!q) return true;
    const haystack = [
        pkg.vendor || '',
        pkg.package_name || '',
        pkg.date || '',
        pkg.package_note || '',
        ...(pkg.blocks || []).map(b => b.delivery_name || b.original_name || ''),
        ...(pkg.blocks || []).map(b => b.note || ''),
        ...(pkg.blocks || []).flatMap(b => b.scenes || []),
        ...(pkg.blocks || []).map(b => b.code || ''),
        ...(pkg.blocks || []).map(b => b.description || ''),
    ].join(' ').toLowerCase();
    return haystack.includes(q);
}}

async function loadDelivered() {{
    const el = document.getElementById('delivered-content');
    if (!el) return;
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⏳</div><p>Loading…</p></div>';
    try {{
        const res  = await fetch('/api/delivered-packages');
        const data = await res.json();
        deliveredPackages = data.packages || [];
        renderDelivered();
    }} catch(e) {{
        el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>Could not load packages: ${{escHtml(e.message)}}</p></div>`;
    }}
}}

function renderDelivered() {{
    const el = document.getElementById('delivered-content');
    if (!el) return;
    const filtered = deliveredPackages.filter(p => pkgMatches(p, deliveredQuery));

    if (filtered.length === 0) {{
        el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📦</div><p>No delivered packages found.</p></div>';
        return;
    }}

    // Group packages
    const groups = {{}};
    filtered.forEach(pkg => {{
        let key;
        if (deliveredMode === 'vendor')     key = pkg.vendor || 'Unknown';
        else if (deliveredMode === 'date')  key = (pkg.date || '').slice(0,6) || 'Unknown';  // YYYYMM
        else if (deliveredMode === 'scene') {{
            const scenes = (pkg.blocks || []).flatMap(b => b.scenes || []);
            const uniq   = [...new Set(scenes)];
            key = uniq.length ? uniq.sort().join(', ') : '—';
        }} else {{
            const codes = (pkg.blocks || []).map(b => b.code).filter(Boolean);
            const uniq  = [...new Set(codes)];
            key = uniq.length ? uniq.sort().join(', ') : '—';
        }}
        if (!groups[key]) groups[key] = [];
        groups[key].push(pkg);
    }});

    const sortedKeys = Object.keys(groups).sort().reverse();
    el.innerHTML = sortedKeys.map(key => {{
        const pkgs = groups[key];
        const cards = pkgs.map(renderDeliveredCard).join('');
        let label = key;
        if (deliveredMode === 'date' && key.length === 6) {{
            const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
            label = `${{months[parseInt(key.slice(4),10)-1]}} ${{key.slice(0,4)}}`;
        }}
        const countLabel = `${{pkgs.length}} package${{pkgs.length === 1 ? '' : 's'}}`;
        return `<div class="group">
            <div class="group-header">
                <span>📦 ${{escHtml(label)}}</span>
                <span class="group-count">${{countLabel}}</span>
            </div>
            ${{cards}}
        </div>`;
    }}).join('');
}}

function renderDeliveredCard(pkg) {{
    const version = pkg.version > 1 ? `<span class="del-version">v${{String(pkg.version).padStart(2,'0')}}</span>` : '';
    const blocks  = pkg.blocks || [];
    const bc      = blocks.length;
    const ts      = pkg.timestamp ? pkg.timestamp.replace('T',' ') : '';
    const pkgUid  = `${{pkg.vendor}}_${{pkg.package_name}}_${{pkg.date}}_${{pkg.version}}`;

    const blockEntries = blocks.map((b, i) => {{
        const blockId   = `${{pkgUid}}_${{i}}`;
        const isExpanded = expandedDelBlocks.has(blockId);
        const name      = escHtml(b.delivery_name || b.original_name || '');
        const scenes    = (b.scenes || []).map(s =>
            `<span class="title-scene">${{escHtml(s)}}</span>`
        ).join('');
        const code = b.code
            ? b.code.split('_').map(c => `<span class="title-code">${{escHtml(c)}}</span>`).join('')
            : '';
        const note = b.note ? `<span class="del-block-note">— ${{escHtml(b.note)}}</span>` : '';
        const chevron = `<button class="toggle-btn" style="margin-left:auto"
            onclick="toggleDelBlock(this)" title="Expand / Collapse">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"/>
            </svg></button>`;
        const subdirs = b.subdirs || [];
        return `<div class="entry${{isExpanded ? ' expanded' : ''}}" data-del-block-id="${{escHtml(blockId)}}">
            <div class="entry-title-line">
                <span class="del-block-name">${{name}}</span>${{scenes}}${{code}}${{note}}${{chevron}}
            </div>
            ${{renderSummary(subdirs)}}
            <div class="entry-details">${{renderSubdirs(subdirs)}}</div>
        </div>`;
    }}).join('');

    const pkgNote = pkg.package_note
        ? `<div class="del-pkg-note">📝 ${{escHtml(pkg.package_note)}}</div>` : '';
    const outPath = pkg.output_path
        ? `<div style="font-size:0.72em;color:var(--text-muted);margin-top:6px;word-break:break-all">${{escHtml(pkg.output_path)}}</div>` : '';

    return `<div class="del-entry">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
            <span class="del-vendor-badge">${{escHtml(pkg.vendor || '')}}</span>
            <span class="del-name-badge">${{escHtml(pkg.package_name || '')}}</span>
            <span class="del-date-badge">${{pkg.date || ''}}</span>
            ${{version}}
            <span style="font-size:0.8em;color:var(--text-muted)">${{bc}} block${{bc===1?'':'s'}}</span>
            <span style="margin-left:auto;font-size:0.74em;color:var(--text-muted)">${{ts}}</span>
        </div>
        ${{blockEntries}}
        ${{pkgNote}}${{outPath}}
    </div>`;
}}

function toggleDelBlock(btn) {{
    const entry = btn.closest('.entry');
    const id    = entry.dataset.delBlockId;
    const expanded = entry.classList.toggle('expanded');
    if (expanded) expandedDelBlocks.add(id);
    else          expandedDelBlocks.delete(id);
}}

// ── Database view ─────────────────────────────────────────────────────────────
let dbRows         = [];
let dbGroupMode    = 'scene';
let dbSortKey      = 'scene';
let dbSortAsc      = true;
let dbFilters      = {{ slate: '', vfx_id: '', date: '', shoot_day: '', roll: '', lens: '', focal: '' }};
let dbQuery        = '';
const expandedDbRows = new Set();

const DB_KEY_FIELDS = ['Slate', 'VFX ID', 'Date', 'Shoot Day', 'Roll', 'Lens', 'Focal'];

const DB_SECTIONS = [
    {{ label: 'DESCRIPTION', rows: [
        ['Scene Description', 'Notes', 'VFX Work'],
    ]}},
    {{ label: 'SET REFS', rows: [['Set Refs']], tagsField: 'Set Refs' }},
    {{ label: 'SLATE', rows: [
        ['Slate', 'VFX ID', 'Take', 'Roll'],
        ['Take Notes'],
    ]}},
    {{ label: 'CAMERA', rows: [
        ['Camera', 'Body', 'Camera Move', 'Resolution'],
    ]}},
    {{ label: 'LENS', rows: [
        ['Lens', 'Focal', 'F-Stop', 'Focus'],
        ['Tilt', 'Height'],
        ['Shutter', 'FPS', 'WB', 'ISO', 'Filter'],
    ]}},
    {{ label: 'LOCATION', rows: [
        ['Shoot Day', 'Date'],
        ['Set Location', 'Script Location'],
        ['Int/Ext', 'Day/Night'],
    ]}},
    {{ label: 'INFOS', rows: [
        ['Unit', 'Wrangler', 'Timestamp'],
    ], includeOthers: true }},
];

function setDbGroup(mode) {{
    dbGroupMode = mode;
    ['scene','vfx_id','date','shoot_day','lens','focal'].forEach(m => {{
        document.getElementById(`db-grp-${{m}}`).classList.toggle('active', m === mode);
    }});
    renderDatabase();
}}

function setDbSort(key) {{
    dbSortKey = key;
    renderDatabase();
}}

function toggleDbSortDir() {{
    dbSortAsc = !dbSortAsc;
    document.getElementById('db-sort-dir').textContent = dbSortAsc ? '↑' : '↓';
    renderDatabase();
}}

function setDbFilter(key, val) {{
    dbFilters[key] = val.trim().toLowerCase();
    renderDatabase();
}}

function setDbQuery(val) {{
    dbQuery = val.trim().toLowerCase();
    document.getElementById('db-search-clear').style.display = val ? 'flex' : 'none';
    renderDatabase();
}}

function clearDbSearch() {{
    const el = document.getElementById('db-global-search');
    if (el) el.value = '';
    setDbQuery('');
}}

function dbRowMatches(row) {{
    const f = dbFilters;
    if (f.slate     && !(row['Slate']      || '').toLowerCase().includes(f.slate))     return false;
    if (f.vfx_id    && !(row['VFX ID']     || '').toLowerCase().includes(f.vfx_id))    return false;
    if (f.date      && !(row['Date']       || '').toLowerCase().includes(f.date))       return false;
    if (f.shoot_day && !(row['Shoot Day']  || '').toLowerCase().includes(f.shoot_day)) return false;
    if (f.roll      && !(row['Roll']       || '').toLowerCase().includes(f.roll))       return false;
    if (f.lens      && !(row['Lens']       || '').toLowerCase().includes(f.lens))       return false;
    if (f.focal     && !(row['Focal']      || '').toLowerCase().includes(f.focal))      return false;
    if (dbQuery) {{
        const others = Object.entries(row)
            .filter(([ k ]) => !DB_KEY_FIELDS.includes(k))
            .map(([ , v ]) => v).join(' ').toLowerCase();
        if (!others.includes(dbQuery)) return false;
    }}
    return true;
}}

function dbGroupKey(row) {{
    switch (dbGroupMode) {{
        case 'scene': {{
            const m = (row['Slate'] || '').match(/^(\\d+)/);
            return m ? `Scene ${{m[1]}}` : (row['Slate'] || '—');
        }}
        case 'vfx_id':    return row['VFX ID']    || '—';
        case 'date':      return row['Date']       || '—';
        case 'shoot_day': return `Day ${{row['Shoot Day'] || '—'}}`;
        case 'lens':      return row['Lens']       || '—';
        case 'focal':     return row['Focal']      || '—';
        default:          return '—';
    }}
}}

function dbSortValue(row) {{
    switch (dbSortKey) {{
        case 'scene': {{
            const m = (row['Slate'] || '').match(/^(\\d+)/);
            return m ? parseInt(m[1]) : 9999;
        }}
        case 'slate':  return row['Slate'] || '';
        case 'vfx_id': return row['VFX ID'] || '';
        case 'date':   return row['Date'] || '';
        case 'shoot_day': {{
            const sd = row['Shoot Day'] || '';
            const m  = sd.match(/(\\d+)/);
            const n  = m ? parseInt(m[1]) : 9999;
            return sd.toUpperCase().startsWith('P') ? n + 10000 : n;
        }}
        case 'lens':  return row['Lens'] || '';
        case 'focal': {{
            const m = (row['Focal'] || '').match(/(\\d+)/);
            return m ? parseInt(m[1]) : 9999;
        }}
        default: return '';
    }}
}}

async function loadDatabase() {{
    const el = document.getElementById('database-content');
    if (!el) return;
    if (dbRows.length > 0) {{ renderDatabase(); return; }}
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⏳</div><p>Loading…</p></div>';
    try {{
        const res  = await fetch('/api/database');
        const data = await res.json();
        dbRows = data.rows || [];
        renderDatabase();
    }} catch(e) {{
        el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>Could not load database: ${{escHtml(e.message)}}</p></div>`;
    }}
}}

function renderDatabase() {{
    const el = document.getElementById('database-content');
    if (!el) return;

    const filtered = dbRows.filter(dbRowMatches);
    if (filtered.length === 0) {{
        el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📋</div><p>No rows match the current filters.</p></div>';
        return;
    }}

    const sorted = [...filtered].sort((a, b) => {{
        const av = dbSortValue(a), bv = dbSortValue(b);
        let cmp;
        if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
        else cmp = String(av).localeCompare(String(bv));
        return dbSortAsc ? cmp : -cmp;
    }});

    const groupKeys = [];
    const groups    = {{}};
    sorted.forEach(row => {{
        const key = dbGroupKey(row);
        if (!groups[key]) {{ groups[key] = []; groupKeys.push(key); }}
        groups[key].push(row);
    }});

    el.innerHTML = groupKeys.map(key => {{
        const rows   = groups[key];
        const cards  = rows.map(row => renderDbCard(row, dbRows.indexOf(row))).join('');
        const countLabel = `${{rows.length}} take${{rows.length === 1 ? '' : 's'}}`;
        return `<div class="group">
            <div class="group-header">
                <span>🎬 ${{escHtml(key)}}</span>
                <span class="group-count">${{countLabel}}</span>
            </div>
            ${{cards}}
        </div>`;
    }}).join('');
}}

function renderDbCard(row, idx) {{
    const id         = `db_${{idx}}`;
    const isExpanded = expandedDbRows.has(id);
    const slate  = row['Slate']     || '—';
    const vfxId  = row['VFX ID']   || '';
    const date   = row['Date']      || '—';
    const day    = row['Shoot Day'] || '—';
    const roll   = row['Roll']      || '';
    const lens   = row['Lens']      || '—';
    const focal  = row['Focal']     || '—';
    const tilt   = row['Tilt']      || '';
    const chevron = `<button class="toggle-btn" style="margin-left:auto"
        onclick="toggleDbCard(this)" title="Expand / Collapse">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"/>
        </svg></button>`;
    return `<div class="entry${{isExpanded ? ' expanded' : ''}}" data-db-id="${{escHtml(id)}}">
        <div class="entry-title-line">
            <span class="db-slate">${{escHtml(slate)}}</span>
            ${{vfxId  ? `<span class="db-vfxid">${{escHtml(vfxId)}}</span>` : ''}}
            <span class="db-date">${{escHtml(date)}}</span>
            <span class="db-day">${{escHtml(day)}}</span>
            ${{roll   ? `<span class="db-roll">${{escHtml(roll)}}</span>` : ''}}
            <span class="db-lens">${{escHtml(lens)}}</span>
            <span class="db-focal">${{escHtml(focal)}}</span>
            ${{tilt   ? `<span class="db-tilt">${{escHtml(tilt)}}</span>` : ''}}
            ${{chevron}}
        </div>
        <div class="entry-details">${{renderDbDetails(row)}}</div>
    </div>`;
}}

function renderDbField(f, v) {{
    return `<span class="db-field">
        <span class="db-field-label">${{escHtml(f)}}</span>
        <span class="db-field-value${{v ? '' : ' empty'}}">${{escHtml(v || '—')}}</span>
    </span>`;
}}

function renderDbDetails(row) {{
    const coveredFields = new Set(DB_SECTIONS.flatMap(s =>
        s.tagsField ? [s.tagsField] : s.rows.flat()
    ));
    const otherFields = Object.keys(row).filter(k => !coveredFields.has(k));

    const sections = DB_SECTIONS.map(sec => {{
        let rowsHtml;

        if (sec.tagsField) {{
            const raw  = (row[sec.tagsField] || '').trim();
            const tags = raw ? raw.split(/[,;]/).map(t => t.trim()).filter(Boolean) : [];
            rowsHtml = `<div class="db-row">${{
                tags.length
                    ? tags.map(t => `<span class="db-tag">${{escHtml(t)}}</span>`).join('')
                    : '<span class="db-field-value empty">—</span>'
            }}</div>`;
        }} else {{
            rowsHtml = sec.rows.map(fields => {{
                const cells = fields.map(f => renderDbField(f, (row[f] || '').trim())).join('');
                return `<div class="db-row">${{cells}}</div>`;
            }}).join('');

            if (sec.includeOthers && otherFields.length) {{
                const cells = otherFields.map(f => renderDbField(f, (row[f] || '').trim())).join('');
                rowsHtml += `<div class="db-row">${{cells}}</div>`;
            }}
        }}

        return `<div class="db-section">
            <div class="db-section-label">${{escHtml(sec.label)}}</div>
            ${{rowsHtml}}
        </div>`;
    }}).join('');
    return `<div class="db-details">${{sections}}</div>`;
}}

function toggleDbCard(btn) {{
    const entry    = btn.closest('.entry');
    const id       = entry.dataset.dbId;
    const expanded = entry.classList.toggle('expanded');
    if (expanded) expandedDbRows.add(id);
    else          expandedDbRows.delete(id);
}}

function renderQueue() {{
    const queue   = loadQueue();
    const listEl  = document.getElementById('queue-list');
    const labelEl = document.getElementById('queue-count-label');
    if (!listEl) return;

    if (labelEl)
        labelEl.textContent = `${{queue.length}} package${{queue.length === 1 ? '' : 's'}} pending`;

    if (queue.length === 0) {{
        listEl.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">📋</div>
            <p>No pending packages — add blocks to the cart and click <strong>Save to Queue</strong>.</p>
        </div>`;
        return;
    }}

    listEl.innerHTML = queue.map(pkg => {{
        const bc = pkg.blocks.length;
        return `<div class="queue-item" data-id="${{pkg.id}}">
            <input type="checkbox" class="queue-cb"
                onchange="this.closest('.queue-item').classList.toggle('selected',this.checked)">
            <div class="queue-item-info">
                <span class="queue-vendor">${{escHtml(pkg.vendor)}}</span>
                <span class="queue-name">${{escHtml(pkg.package_name)}}</span>
                <span class="queue-date">${{escHtml(pkg.date)}}</span>
                <span class="queue-meta">${{bc}} block${{bc === 1 ? '' : 's'}}</span>
                ${{pkg.package_note ? `<span class="queue-meta" title="${{escHtml(pkg.package_note)}}">📝 note</span>` : ''}}
            </div>
            <div class="queue-item-actions">
                <button class="queue-edit-btn"
                    onclick="editPending(${{pkg.id}})">Edit</button>
                <button class="queue-delete-btn"
                    onclick="deletePending(${{pkg.id}})">Delete</button>
            </div>
        </div>`;
    }}).join('');
}}

function deletePending(id) {{
    saveQueue(loadQueue().filter(p => p.id !== id));
    renderQueue();
}}

function restoreVendorToForm(vendor) {{
    const sel      = document.getElementById('pkg-vendor-select');
    const customEl = document.getElementById('pkg-vendor-custom');
    const vendors  = deliveryCfg.vendors || [];
    if (sel.style.display !== 'none' && vendors.includes(vendor)) {{
        sel.value = vendor; customEl.style.display = 'none';
    }} else if (sel.style.display !== 'none') {{
        sel.value = '__custom__'; customEl.style.display = 'block'; customEl.value = vendor;
    }} else {{
        customEl.value = vendor;
    }}
}}

function editPending(id) {{
    const queue = loadQueue();
    const pkg   = queue.find(p => p.id === id);
    if (!pkg) return;

    saveQueue(queue.filter(p => p.id !== id));
    clearCart();

    const missing = [];
    for (const block of pkg.blocks) {{
        if (allEntries[block.path]) {{
            cart.set(block.path, {{ entry: allEntries[block.path], note: block.note || '' }});
        }} else {{
            missing.push(block.delivery_name || block.path);
        }}
    }}
    cartSave();

    restoreVendorToForm(pkg.vendor);
    document.getElementById('pkg-name').value           = pkg.package_name;
    document.getElementById('pkg-date').value           = pkg.date;
    document.getElementById('pkg-output-dir').value     = pkg.output_dir;
    document.getElementById('package-note-input').value = pkg.package_note || '';
    savePackageNote(pkg.package_note || '');

    renderCart();
    setView('browse');

    if (missing.length)
        showBuildStatus('error',
            `⚠️ ${{missing.length}} block(s) not found in current data:\\n${{missing.join('\\n')}}`);
}}

function toggleSelectAll() {{
    const cbs = document.querySelectorAll('.queue-cb');
    const anyUnchecked = [...cbs].some(cb => !cb.checked);
    cbs.forEach(cb => {{
        cb.checked = anyUnchecked;
        cb.closest('.queue-item').classList.toggle('selected', anyUnchecked);
    }});
}}

async function buildSelected() {{
    const selected = [...document.querySelectorAll('.queue-cb:checked')]
        .map(cb => parseInt(cb.closest('.queue-item').dataset.id));

    if (selected.length === 0) {{
        alert('Select at least one package to build.');
        return;
    }}

    const toProcess = loadQueue().filter(p => selected.includes(p.id));
    const btn    = document.getElementById('queue-build-btn');
    const progEl = document.getElementById('build-progress');

    btn.disabled = true;
    progEl.className = 'running';
    progEl.style.display = 'block';
    progEl.textContent = `Building 0 / ${{toProcess.length}}…`;

    const errors = [];
    let done = 0;

    for (const pkg of toProcess) {{
        progEl.textContent =
            `Building ${{done + 1}} / ${{toProcess.length}}: ${{pkg.vendor}} / ${{pkg.package_name}}…`;
        try {{
            const res  = await fetch('/api/build-package', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{
                    vendor:       pkg.vendor,
                    package_name: pkg.package_name,
                    date:         pkg.date,
                    output_dir:   pkg.output_dir,
                    package_note: pkg.package_note,
                    blocks:       pkg.blocks,
                }}),
            }});
            const data = await res.json();
            if (data.success) {{
                saveQueue(loadQueue().filter(p => p.id !== pkg.id));
                done++;
            }} else {{
                errors.push(`${{pkg.vendor}}/${{pkg.package_name}}: ${{(data.errors || [data.error || 'error']).join(', ')}}`);
            }}
        }} catch(e) {{
            errors.push(`${{pkg.vendor}}/${{pkg.package_name}}: Network error — ${{e.message}}`);
        }}
        renderQueue();
    }}

    btn.disabled = false;
    if (errors.length === 0) {{
        progEl.className = 'done-ok';
        progEl.textContent = `✓ Built ${{done}} package${{done === 1 ? '' : 's'}} successfully.`;
    }} else {{
        progEl.className = 'done-err';
        progEl.textContent =
            `✓ ${{done}} built   ✗ ${{errors.length}} failed:\\n${{errors.join('\\n')}}`;
    }}
}}

cartLoad();
loadPackageNote();
loadBuildForm();
renderCart();
updateQueueBadge();

render();

// ── Slate extraction ──────────────────────────────────────────────────────────
async function checkExtractStatus() {{
    try {{
        const res  = await fetch('/api/extract-slates-status');
        const data = await res.json();
        const btn  = document.getElementById('extract-slates-btn');
        if (!btn) return;
        if (data.needs_refresh) {{
            btn.classList.add('needs-refresh');
            btn.title = `DB updated ${{data.db_date}} — extraction needed`;
        }} else {{
            btn.classList.remove('needs-refresh');
            btn.title = data.db_date ? `Slates extracted from ${{data.db_date}}` : 'No database CSV found';
        }}
    }} catch(e) {{ /* fail silently */ }}
}}

async function runExtractSlates() {{
    const btn    = document.getElementById('extract-slates-btn');
    const status = document.getElementById('extract-status');
    if (btn) {{ btn.disabled = true; btn.textContent = '⏳ Extracting…'; }}
    if (status) {{ status.textContent = ''; status.className = 'extract-status'; }}
    try {{
        const res  = await fetch('/api/extract-slates', {{ method: 'POST' }});
        const data = await res.json();
        if (data.success) {{
            if (status) {{
                const errs = data.errors && data.errors.length ? ` (${{data.errors.length}} errors)` : '';
                status.textContent = `✓ ${{data.updated}} blocks updated, ${{data.skipped}} skipped${{errs}}`;
                status.className = 'extract-status ok';
                setTimeout(() => {{ if (status) {{ status.textContent = ''; status.className = 'extract-status'; }} }}, 6000);
            }}
            checkExtractStatus();
        }} else {{
            if (status) {{ status.textContent = `✗ ${{data.error || 'Failed'}}`; status.className = 'extract-status err'; }}
        }}
    }} catch(e) {{
        if (status) {{ status.textContent = '✗ Network error'; status.className = 'extract-status err'; }}
    }} finally {{
        if (btn) {{ btn.disabled = false; btn.textContent = '📊 Extract Slates'; }}
    }}
}}

checkExtractStatus();
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
