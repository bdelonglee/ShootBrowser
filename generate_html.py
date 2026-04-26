#!/usr/bin/env python3
"""
VFX Shoot Data HTML Generator
Generates an interactive HTML page to browse shoot data by days, scenes, or codes
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set
from dataclasses import dataclass, asdict
from collections import defaultdict
from datetime import datetime


@dataclass
class ShootEntry:
    """Information about a shoot day directory"""
    path: str
    directory_name: str
    day: str  # JXX or PJXX
    scenes: List[str]  # List of SXX
    code: str  # 4-letter code
    description: str
    has_data: bool  # True if directory contains files
    subdirectories: List[str]  # List of subdirectory names


class HTMLGenerator:
    """Generate interactive HTML page for VFX shoot data"""

    # Regex pattern for directory names
    DIR_PATTERN = re.compile(
        r'^(J\d{2}|PJ\d{2})__(S\d{2}(?:_S\d{2})*)__([A-Z]{4}(?:_[A-Z]{4})*)__(.+)$'
    )

    # Directories to skip
    SKIP_DIRS = {'TODO__', '__RAPPORTS_SCRIPT', '__Souvenirs_Vrac', '__CALLSHEETS'}

    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.entries: List[ShootEntry] = []

    def check_has_data(self, dir_path: Path) -> bool:
        """Check if directory contains any files (not just subdirectories)"""
        for root, dirs, files in os.walk(dir_path):
            # Ignore hidden files starting with ._
            visible_files = [f for f in files if not f.startswith('._')]
            if visible_files:
                return True
        return False

    def get_subdirectories(self, dir_path: Path) -> List[str]:
        """Get list of immediate subdirectories"""
        subdirs = []
        try:
            for item in dir_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    subdirs.append(item.name)
        except PermissionError:
            pass
        return sorted(subdirs)

    def parse_directories(self):
        """Parse all day directories and collect data"""
        print("📂 Parsing shoot directories...")

        for item in self.data_path.iterdir():
            if not item.is_dir():
                continue

            # Skip special directories
            if any(skip in item.name for skip in self.SKIP_DIRS):
                continue

            # Skip template
            if item.name == 'J00_TEMPLATE':
                continue

            # Parse directory name
            match = self.DIR_PATTERN.match(item.name)
            if not match:
                continue

            day = match.group(1)
            scenes_str = match.group(2)
            code = match.group(3)
            description = match.group(4)

            scenes = scenes_str.split('_')

            # Check if directory has data
            has_data = self.check_has_data(item)

            # Get subdirectories
            subdirs = self.get_subdirectories(item)

            entry = ShootEntry(
                path=str(item),
                directory_name=item.name,
                day=day,
                scenes=scenes,
                code=code,
                description=description,
                has_data=has_data,
                subdirectories=subdirs
            )

            self.entries.append(entry)

        print(f"   Found {len(self.entries)} shoot entries")

    def organize_by_days(self) -> Dict[str, List[ShootEntry]]:
        """Organize entries by day"""
        by_day = defaultdict(list)
        for entry in self.entries:
            by_day[entry.day].append(entry)
        return dict(sorted(by_day.items()))

    def organize_by_scenes(self) -> Dict[str, List[ShootEntry]]:
        """Organize entries by scene"""
        by_scene = defaultdict(list)
        for entry in self.entries:
            for scene in entry.scenes:
                by_scene[scene].append(entry)
        return dict(sorted(by_scene.items()))

    def organize_by_codes(self) -> Dict[str, List[ShootEntry]]:
        """Organize entries by code"""
        by_code = defaultdict(list)
        for entry in self.entries:
            # Handle multi-codes (e.g., RIDE_DAME)
            codes = entry.code.split('_')
            for code in codes:
                by_code[code].append(entry)
        return dict(sorted(by_code.items()))

    def generate_html(self, output_path: str):
        """Generate the HTML page"""
        print(f"🎨 Generating HTML page...")

        # Organize data
        by_days = self.organize_by_days()
        by_scenes = self.organize_by_scenes()
        by_codes = self.organize_by_codes()

        # Convert to JSON for embedding in HTML
        data = {
            'by_days': {k: [asdict(e) for e in v] for k, v in by_days.items()},
            'by_scenes': {k: [asdict(e) for e in v] for k, v in by_scenes.items()},
            'by_codes': {k: [asdict(e) for e in v] for k, v in by_codes.items()},
        }

        # Generate HTML
        html = self._generate_html_template(data)

        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"   Saved to: {output_path}")

    def _generate_html_template(self, data: dict) -> str:
        """Generate the complete HTML template"""
        data_json = json.dumps(data, indent=2)
        generated_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VFX Shoot Data Browser</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: #333;
            padding: 20px;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        header {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }}

        h1 {{
            color: #1e3c72;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}

        .subtitle {{
            color: #666;
            font-size: 1.1em;
        }}

        .controls {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
        }}

        .mode-button {{
            background: #f0f0f0;
            border: 2px solid #ddd;
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: all 0.3s ease;
        }}

        .mode-button:hover {{
            background: #e0e0e0;
            transform: translateY(-2px);
        }}

        .mode-button.active {{
            background: #1e3c72;
            color: white;
            border-color: #1e3c72;
        }}

        .stats {{
            margin-left: auto;
            display: flex;
            gap: 20px;
        }}

        .stat {{
            text-align: center;
        }}

        .stat-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #1e3c72;
        }}

        .stat-label {{
            font-size: 0.9em;
            color: #666;
        }}

        .content {{
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            min-height: 500px;
        }}

        .group {{
            margin-bottom: 30px;
        }}

        .group-header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            font-size: 1.3em;
            font-weight: bold;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .group-count {{
            background: rgba(255, 255, 255, 0.2);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 0.8em;
        }}

        .entry {{
            background: #f8f9fa;
            border-left: 4px solid #1e3c72;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            transition: all 0.3s ease;
        }}

        .entry:hover {{
            background: #e9ecef;
            transform: translateX(5px);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}

        .entry-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 12px;
        }}

        .entry-title {{
            font-size: 1.1em;
            font-weight: bold;
            color: #1e3c72;
            font-family: 'Monaco', 'Courier New', monospace;
        }}

        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}

        .badge-day {{
            background: #d4edda;
            color: #155724;
        }}

        .badge-scene {{
            background: #d1ecf1;
            color: #0c5460;
        }}

        .badge-code {{
            background: #fff3cd;
            color: #856404;
        }}

        .badge-has-data {{
            background: #28a745;
            color: white;
        }}

        .badge-empty {{
            background: #6c757d;
            color: white;
        }}

        .entry-description {{
            color: #555;
            margin-bottom: 10px;
        }}

        .entry-subdirs {{
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
        }}

        .subdir-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
            font-weight: 600;
        }}

        .subdir-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}

        .subdir-item {{
            background: white;
            border: 1px solid #ddd;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.85em;
            font-family: 'Monaco', 'Courier New', monospace;
        }}

        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }}

        .empty-state-icon {{
            font-size: 4em;
            margin-bottom: 20px;
        }}

        footer {{
            text-align: center;
            margin-top: 30px;
            color: white;
            opacity: 0.8;
        }}

        @media (max-width: 768px) {{
            .stats {{
                margin-left: 0;
                width: 100%;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 VFX Shoot Data Browser</h1>
            <p class="subtitle">Interactive browser for shoot data organized by days, scenes, and codes</p>
        </header>

        <div class="controls">
            <button class="mode-button active" onclick="setMode('days')" id="btn-days">
                📅 By Days
            </button>
            <button class="mode-button" onclick="setMode('scenes')" id="btn-scenes">
                🎞️ By Scenes
            </button>
            <button class="mode-button" onclick="setMode('codes')" id="btn-codes">
                🏷️ By Codes
            </button>

            <div class="stats">
                <div class="stat">
                    <div class="stat-value" id="stat-total">0</div>
                    <div class="stat-label">Total Entries</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="stat-groups">0</div>
                    <div class="stat-label">Groups</div>
                </div>
            </div>
        </div>

        <div class="content" id="content">
            <div class="empty-state">
                <div class="empty-state-icon">📂</div>
                <p>Loading...</p>
            </div>
        </div>

        <footer>
            Generated on {generated_time}
        </footer>
    </div>

    <script>
        const data = {data_json};

        let currentMode = 'days';

        function setMode(mode) {{
            currentMode = mode;

            // Update button states
            document.querySelectorAll('.mode-button').forEach(btn => {{
                btn.classList.remove('active');
            }});
            document.getElementById(`btn-${{mode}}`).classList.add('active');

            // Render content
            renderContent();
        }}

        function renderContent() {{
            const contentEl = document.getElementById('content');
            const modeData = data[`by_${{currentMode}}`];

            if (!modeData || Object.keys(modeData).length === 0) {{
                contentEl.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📂</div>
                        <p>No data found</p>
                    </div>
                `;
                updateStats(0, 0);
                return;
            }}

            let html = '';
            let totalEntries = 0;
            const groups = Object.keys(modeData).length;

            for (const [key, entries] of Object.entries(modeData)) {{
                totalEntries += entries.length;

                html += `
                    <div class="group">
                        <div class="group-header">
                            <span>${{getGroupIcon(currentMode)}} ${{key}}</span>
                            <span class="group-count">${{entries.length}} ${{entries.length === 1 ? 'entry' : 'entries'}}</span>
                        </div>
                `;

                entries.forEach(entry => {{
                    html += renderEntry(entry);
                }});

                html += '</div>';
            }}

            contentEl.innerHTML = html;
            updateStats(totalEntries, groups);
        }}

        function renderEntry(entry) {{
            const scenesHtml = entry.scenes.map(s =>
                `<span class="badge badge-scene">${{s}}</span>`
            ).join(' ');

            const codesHtml = entry.code.split('_').map(c =>
                `<span class="badge badge-code">${{c}}</span>`
            ).join(' ');

            const dataStatus = entry.has_data
                ? '<span class="badge badge-has-data">Has Data</span>'
                : '<span class="badge badge-empty">Empty</span>';

            let subdirsHtml = '';
            if (entry.subdirectories && entry.subdirectories.length > 0) {{
                const subdirItems = entry.subdirectories.map(sd =>
                    `<span class="subdir-item">${{sd}}</span>`
                ).join('');

                subdirsHtml = `
                    <div class="entry-subdirs">
                        <div class="subdir-label">📁 Subdirectories (${{entry.subdirectories.length}}):</div>
                        <div class="subdir-list">${{subdirItems}}</div>
                    </div>
                `;
            }}

            return `
                <div class="entry">
                    <div class="entry-header">
                        <span class="badge badge-day">${{entry.day}}</span>
                        ${{scenesHtml}}
                        ${{codesHtml}}
                        ${{dataStatus}}
                    </div>
                    <div class="entry-title">${{entry.directory_name}}</div>
                    <div class="entry-description">${{entry.description}}</div>
                    ${{subdirsHtml}}
                </div>
            `;
        }}

        function getGroupIcon(mode) {{
            const icons = {{
                'days': '📅',
                'scenes': '🎞️',
                'codes': '🏷️'
            }};
            return icons[mode] || '📂';
        }}

        function updateStats(total, groups) {{
            document.getElementById('stat-total').textContent = total;
            document.getElementById('stat-groups').textContent = groups;
        }}

        // Initialize
        renderContent();
    </script>
</body>
</html>"""

        return html


def main():
    """Main entry point"""
    import sys

    # Default data path
    data_path = "/Volumes/MACGUFF001/POSEIDON/DATA_rename"
    output_path = "vfx_shoot_browser.html"

    # Allow override from command line
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
    print(f"   Open {output_path} in your browser to view\n")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
