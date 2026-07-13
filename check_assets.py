#!/usr/bin/env python3
"""
ASSETS_SHOOT sanity checker.

Convention: a directory prefixed with __ is considered empty.
When files are added inside a directory, the __ prefix must be removed
from that directory AND all its ancestors up to the asset level.

Checks:
  A. Empty directory (no real files anywhere in subtree) must have __ prefix.
  B. Non-empty directory (has real files) must NOT have __ prefix.
  C. Files found directly at the root of a data directory should be in a named subdir.
  D. Each non-empty data directory should have at least one user-named subdir (no spaces).
  E. Spaces in non-template directory names → propose rename.
  F. Files directly at the asset root level → warning.

Usage:
  python check_assets.py
  python check_assets.py --path /path/to/ASSETS_SHOOT
  python check_assets.py --root /path/to/STRUCTURE   # uses STRUCTURE/ASSETS_SHOOT
  python check_assets.py --dry-run                   # report only, no prompts
"""

import re
import sys
import json
import argparse
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

PREFIX      = '__'
SKIP_TYPES  = {'cameras'}          # stripped, lowercased type-dir names to skip
SKIP_ASSETS = {'TO_SORT'}          # asset dir names to skip (exact match)
# Data-category dirs where files are allowed directly at root (no named subdir required)
FILES_AT_ROOT_OK = {'10_Infos', '__10_Infos'}
DEFAULT_REL = 'ASSETS_SHOOT'       # relative to PROJECT_ROOT / STRUCTURE root

# ── Path helpers ──────────────────────────────────────────────────────────────

_remap: dict[str, str] = {}        # tracks applied renames: old_abs → new_abs


def _remap_path(p: Path) -> Path:
    """Return the current on-disk path of p after any already-applied renames."""
    s = str(p)
    for old, new in sorted(_remap.items(), key=lambda x: -len(x[0])):
        if s.startswith(old):
            s = new + s[len(old):]
            break
    return Path(s)


def _strip_num(name: str) -> str:
    """'10_PROPS' → 'PROPS'"""
    return re.sub(r'^\d+_', '', name)


def _is_real_file(p: Path) -> bool:
    return p.is_file() and not p.name.startswith('.') and not p.name.startswith('._')


def _subdirs(d: Path) -> list:
    try:
        return sorted([c for c in d.iterdir() if c.is_dir() and not c.name.startswith('.')],
                      key=lambda p: p.name)
    except PermissionError:
        return []


def _direct_files(d: Path) -> list:
    try:
        return [f for f in d.iterdir() if _is_real_file(f)]
    except PermissionError:
        return []


def _has_content(d: Path) -> bool:
    try:
        for f in d.rglob('*'):
            if _is_real_file(f):
                return True
    except PermissionError:
        pass
    return False


# ── Issue ─────────────────────────────────────────────────────────────────────

class Issue:
    __slots__ = ('kind', 'path', 'msg', 'fix_label', '_fix')

    def __init__(self, kind, path, msg, fix_label=None, fix=None):
        self.kind      = kind        # EXTRA_PREFIX | MISSING_PREFIX | SPACE | WARNING
        self.path      = path        # original Path at scan time
        self.msg       = msg
        self.fix_label = fix_label
        self._fix      = fix         # callable() → (old, new) or None

    def apply(self):
        if not self._fix:
            return
        current = _remap_path(self.path)
        if not current.exists():
            print(f'    ↩  Already resolved (parent was renamed): {self.path.name}')
            return
        old, new = self._fix(current)
        if old and new:
            _remap[str(old)] = str(new)
            print(f'    ✓  {old.name}  →  {new.name}')


ICON = {
    'EXTRA_PREFIX':   '❌',
    'MISSING_PREFIX': '⚠ ',
    'SPACE':          '⚠ ',
    'WARNING':        'ℹ ',
}

# ── Fix factories ─────────────────────────────────────────────────────────────

def _fix_remove_prefix(current: Path):
    new = current.parent / current.name[2:]
    current.rename(new)
    return current, new


def _fix_add_prefix(current: Path):
    new = current.parent / (PREFIX + current.name)
    current.rename(new)
    return current, new


def _fix_remove_spaces(current: Path):
    new = current.parent / current.name.replace(' ', '_')
    current.rename(new)
    return current, new


# ── Scanner ───────────────────────────────────────────────────────────────────

def _scan_asset(asset_dir: Path, label: str) -> list:
    issues = []

    # Rule F — files directly at asset root
    for f in _direct_files(asset_dir):
        issues.append(Issue('WARNING', f, f'File at asset root: {label}/{f.name}'))

    def _walk(d: Path, depth: int, parent_is_tmpl_ctx: bool):
        """
        parent_is_tmpl_ctx: True when d is a template-context directory, meaning
        its immediate non-template children are the 'first user level' and should
        be space-checked.  Stays True through nested __ dirs; becomes False once
        we step into a user-created dir.
        """
        for sub in _subdirs(d):
            name        = sub.name
            is_tmpl     = name.startswith(PREFIX)
            content     = _has_content(sub)
            rel         = sub.relative_to(asset_dir)

            # Rule B — non-empty dir still has __ prefix
            if content and is_tmpl:
                issues.append(Issue(
                    'EXTRA_PREFIX', sub,
                    f'Non-empty dir has __ prefix: {label}/{rel}',
                    fix_label=f'Rename: {name}  →  {name[2:]}',
                    fix=_fix_remove_prefix,
                ))

            # Rule A — empty dir missing __ prefix
            elif not content and not is_tmpl:
                issues.append(Issue(
                    'MISSING_PREFIX', sub,
                    f'Empty dir missing __ prefix: {label}/{rel}',
                    fix_label=f'Rename: {name}  →  __{name}',
                    fix=_fix_add_prefix,
                ))

            # Rule E — spaces, only at the first user-created level inside a template context
            if not is_tmpl and ' ' in name and parent_is_tmpl_ctx:
                issues.append(Issue(
                    'SPACE', sub,
                    f'Space in directory name: {label}/{rel}',
                    fix_label=f'Rename: {name}  →  {name.replace(" ", "_")}',
                    fix=_fix_remove_spaces,
                ))

            # Rules C & D — only for populated, non-template, data-category dirs (depth=0)
            if not is_tmpl and content and depth == 0:
                direct = _direct_files(sub)
                user_subs = [s for s in _subdirs(sub) if not s.name.startswith(PREFIX)]

                # Rule C — files dumped directly in a data dir
                if direct and name not in FILES_AT_ROOT_OK:
                    issues.append(Issue(
                        'WARNING', sub,
                        f'{len(direct)} file(s) directly at data dir root — '
                        f'consider a named subdir: {label}/{rel}',
                    ))

                # Rule D — no user-named subdir at all
                if not user_subs and not direct:
                    issues.append(Issue(
                        'WARNING', sub,
                        f'Non-empty data dir has no user-named subdir: {label}/{rel}',
                    ))

            # Propagate template context:
            # - __ dirs keep the context (still inside template territory)
            # - depth-0 dirs are data-category level (template-derived, with or without __ now)
            # - user-created dirs (depth>0, not __) exit the template context
            child_is_tmpl_ctx = is_tmpl or (depth == 0)
            _walk(sub, depth + 1, parent_is_tmpl_ctx=child_is_tmpl_ctx)

    _walk(asset_dir, 0, parent_is_tmpl_ctx=True)
    return issues


def scan(root: Path) -> list:
    all_issues = []
    for type_dir in sorted(root.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith('.'):
            continue
        if _strip_num(type_dir.name).lower() in SKIP_TYPES:
            print(f'  Skipping {type_dir.name}/')
            continue
        for asset_dir in sorted(type_dir.iterdir()):
            if not asset_dir.is_dir() or asset_dir.name.startswith('.'):
                continue
            if asset_dir.name in SKIP_ASSETS:
                print(f'  Skipping {type_dir.name}/{asset_dir.name}/')
                continue
            label = f'{type_dir.name}/{asset_dir.name}'
            all_issues.extend(_scan_asset(asset_dir, label))
    return all_issues


# ── Report & interactive fix ──────────────────────────────────────────────────

def report(issues: list):
    counts = {'EXTRA_PREFIX': 0, 'MISSING_PREFIX': 0, 'SPACE': 0, 'WARNING': 0}
    for i in issues:
        counts[i.kind] += 1
        icon = ICON.get(i.kind, '  ')
        print(f'  {icon}  {i.msg}')
        if i.fix_label:
            print(f'       → {i.fix_label}')
    print()
    print(f'  {counts["EXTRA_PREFIX"]} extra-prefix  |  '
          f'{counts["MISSING_PREFIX"]} missing-prefix  |  '
          f'{counts["SPACE"]} spaces  |  '
          f'{counts["WARNING"]} warnings')


def _prompt(msg: str, options: str) -> str:
    try:
        return input(f'  {msg} [{options}]: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def fix_interactive(issues: list):
    fixable = [i for i in issues if i._fix is not None]
    if not fixable:
        print('\nNo auto-fixable issues.')
        return

    print(f'\n{len(fixable)} auto-fixable issue(s).')
    mode = _prompt('Fix all / review one-by-one / skip all', 'a/r/s')

    if mode == 's':
        return

    # Sort shallowest path first so parent renames happen before children
    ordered = sorted(fixable, key=lambda i: len(i.path.parts))

    fix_all = mode == 'a'
    for issue in ordered:
        if not fix_all:
            print(f'\n  {ICON.get(issue.kind)} {issue.msg}')
            print(f'  Fix: {issue.fix_label}')
            ans = _prompt('Apply?', 'y/n/a=all/q=quit')
            if ans == 'q':
                break
            if ans == 'a':
                fix_all = True
            elif ans != 'y':
                continue
        issue.apply()


# ── Path resolution ───────────────────────────────────────────────────────────

def _resolve_root(args) -> Path:
    if args.path:
        p = Path(args.path).resolve()
        if not p.exists():
            sys.exit(f'Error: path not found: {p}')
        return p

    # Try --root arg or script-relative STRUCTURE
    if args.root:
        structure = Path(args.root).resolve()
    else:
        # Try to find STRUCTURE relative to script location
        script_dir = Path(__file__).resolve().parent
        # server.py lives in python_shoot/ alongside launch.sh
        # PROJECT_ROOT is STRUCTURE (from launch.sh)
        cfg_path = script_dir / 'SHOOT_BROWSER' / 'Config' / 'project_config.json'
        if not cfg_path.exists():
            # Try reading from a sibling launch.sh to guess --root
            launch = script_dir / 'launch.sh'
            if launch.exists():
                m = re.search(r'--root\s+"?([^"]+)"?', launch.read_text())
                if m:
                    structure = Path(m.group(1)).resolve()
                else:
                    sys.exit('Could not detect project root. Use --path or --root.')
            else:
                sys.exit('Could not detect project root. Use --path or --root.')
        else:
            try:
                cfg = json.loads(cfg_path.read_text())
                custom = (cfg.get('paths') or {}).get('assets_shoot', '').strip()
                if custom:
                    return Path(custom).resolve()
            except Exception:
                pass
            structure = script_dir  # fallback: treat script dir as structure root

    p = structure / DEFAULT_REL
    if not p.exists():
        sys.exit(f'Error: ASSETS_SHOOT not found at {p}\nUse --path to specify explicitly.')
    return p


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='ASSETS_SHOOT sanity checker')
    parser.add_argument('--path',    help='Direct path to ASSETS_SHOOT directory')
    parser.add_argument('--root',    help='Path to STRUCTURE directory (uses STRUCTURE/ASSETS_SHOOT)')
    parser.add_argument('--dry-run', action='store_true', help='Report issues only, no fix prompts')
    args = parser.parse_args()

    root = _resolve_root(args)
    print(f'\nScanning: {root}\n')

    issues = scan(root)

    if not issues:
        print('  ✓  No issues found.')
        return

    report(issues)

    if not args.dry_run:
        fix_interactive(issues)


if __name__ == '__main__':
    main()
