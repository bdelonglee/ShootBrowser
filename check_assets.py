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
  python check_assets.py --no-color                  # disable ANSI colors
"""

import re
import sys
import json
import shutil
import argparse
from pathlib import Path

# ── ANSI colors ───────────────────────────────────────────────────────────────

class C:
    RED    = '\033[91m'
    YELLOW = '\033[93m'
    CYAN   = '\033[96m'
    GREEN  = '\033[92m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    RESET  = '\033[0m'

    @classmethod
    def off(cls):
        for a in ('RED', 'YELLOW', 'CYAN', 'GREEN', 'BOLD', 'DIM', 'RESET'):
            setattr(cls, a, '')

# ── Constants ─────────────────────────────────────────────────────────────────

PREFIX      = '__'
SKIP_TYPES  = {'cameras'}          # stripped, lowercased type-dir names to skip
SKIP_ASSETS = {'TO_SORT'}          # asset dir names to skip (exact match)
FILES_AT_ROOT_OK = {'10_Infos', '__10_Infos'}
DEFAULT_REL = 'ASSETS_SHOOT'

# kind → (icon, color-attr)
_KIND = {
    'EXTRA_PREFIX':   ('✗', 'RED'),
    'MISSING_PREFIX': ('▲', 'YELLOW'),
    'SPACE':          ('~', 'CYAN'),
    'WARNING':        ('·', 'DIM'),
}

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
    __slots__ = ('kind', 'label', 'path', 'detail', 'fix_label', '_fix')

    def __init__(self, kind, label, path, detail, fix_label=None, fix=None):
        self.kind      = kind       # EXTRA_PREFIX | MISSING_PREFIX | SPACE | WARNING
        self.label     = label      # 'TYPE/ASSET' — used for grouping in report
        self.path      = path       # original Path at scan time
        self.detail    = detail     # short human-readable description
        self.fix_label = fix_label  # action string shown in interactive mode
        self._fix      = fix        # callable(current_path) → (old, new)

    def apply(self):
        if not self._fix:
            return
        current = _remap_path(self.path)
        if not current.exists():
            print(f'  {C.DIM}↩  already resolved (parent was renamed): {self.path.name}{C.RESET}')
            return
        old, new = self._fix(current)
        if old and new:
            _remap[str(old)] = str(new)
            print(f'  {C.GREEN}✓{C.RESET}  {C.BOLD}{old.name}{C.RESET}  →  {C.GREEN}{new.name}{C.RESET}')


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
        issues.append(Issue('WARNING', label, f, f'file at asset root: {f.name}'))

    def _walk(d: Path, depth: int, parent_is_tmpl_ctx: bool):
        """
        parent_is_tmpl_ctx: True when d is a template-context directory, meaning
        its immediate non-template children are the 'first user level' and should
        be space-checked.  Stays True through nested __ dirs; becomes False once
        we step into a user-created dir.
        """
        for sub in _subdirs(d):
            name    = sub.name
            is_tmpl = name.startswith(PREFIX)
            content = _has_content(sub)
            rel     = sub.relative_to(asset_dir)

            # Rule B — non-empty dir still has __ prefix
            if content and is_tmpl:
                stripped = name[2:]
                issues.append(Issue(
                    'EXTRA_PREFIX', label, sub,
                    f'{name}  →  {stripped}',
                    fix_label=f'rename  {name}  →  {stripped}',
                    fix=_fix_remove_prefix,
                ))

            # Rule A — empty dir missing __ prefix
            elif not content and not is_tmpl:
                issues.append(Issue(
                    'MISSING_PREFIX', label, sub,
                    f'{name}  →  __{name}',
                    fix_label=f'rename  {name}  →  __{name}',
                    fix=_fix_add_prefix,
                ))

            # Rule E — spaces, only at the first user-created level inside a template context
            if not is_tmpl and ' ' in name and parent_is_tmpl_ctx:
                fixed = name.replace(' ', '_')
                issues.append(Issue(
                    'SPACE', label, sub,
                    f'"{name}"  →  {fixed}',
                    fix_label=f'rename  "{name}"  →  {fixed}',
                    fix=_fix_remove_spaces,
                ))

            # Rules C & D — only for populated, non-template, data-category dirs (depth=0)
            if not is_tmpl and content and depth == 0:
                direct    = _direct_files(sub)
                user_subs = [s for s in _subdirs(sub) if not s.name.startswith(PREFIX)]

                # Rule C — files dumped directly in a data dir
                if direct and name not in FILES_AT_ROOT_OK:
                    issues.append(Issue(
                        'WARNING', label, sub,
                        f'{len(direct)} file(s) at root of {rel}/ — use a named subdir',
                    ))

                # Rule D — no user-named subdir at all
                if not user_subs and not direct:
                    issues.append(Issue(
                        'WARNING', label, sub,
                        f'no user-named subdir in {rel}/',
                    ))

            # Propagate template context:
            # - __ dirs keep the context (still inside template territory)
            # - depth-0 dirs are data-category level (template-derived, with or without __ now)
            # - user-created dirs (depth>0, not __) exit the template context
            child_is_tmpl_ctx = is_tmpl or (depth == 0)
            _walk(sub, depth + 1, parent_is_tmpl_ctx=child_is_tmpl_ctx)

    _walk(asset_dir, 0, parent_is_tmpl_ctx=True)
    return issues


def scan(root: Path) -> tuple[list, list, int]:
    """Returns (issues, skipped_labels, scanned_count)."""
    all_issues = []
    skipped    = []
    scanned    = 0
    for type_dir in sorted(root.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith('.'):
            continue
        if _strip_num(type_dir.name).lower() in SKIP_TYPES:
            skipped.append(type_dir.name + '/')
            continue
        for asset_dir in sorted(type_dir.iterdir()):
            if not asset_dir.is_dir() or asset_dir.name.startswith('.'):
                continue
            if asset_dir.name in SKIP_ASSETS:
                skipped.append(f'{type_dir.name} / {asset_dir.name}')
                continue
            scanned += 1
            label = f'{type_dir.name}/{asset_dir.name}'
            all_issues.extend(_scan_asset(asset_dir, label))
    return all_issues, skipped, scanned


# ── Output helpers ────────────────────────────────────────────────────────────

def _width() -> int:
    return min(shutil.get_terminal_size(fallback=(72, 24)).columns, 72)


def _hr(char='─', bold=False):
    line = char * _width()
    print((C.BOLD if bold else C.DIM) + line + C.RESET)


def _section(title: str):
    w   = _width()
    pad = w - len(title) - 4
    print(f'{C.BOLD}── {title}  {C.DIM}{"─" * max(pad, 2)}{C.RESET}')


def _issue_line(issue: Issue) -> str:
    icon, col = _KIND.get(issue.kind, ('·', 'DIM'))
    color     = getattr(C, col)
    return f'  {color}{icon}{C.RESET}  {issue.detail}'


# ── Report ────────────────────────────────────────────────────────────────────

def report(issues: list, scanned: int, skipped: list):
    from collections import OrderedDict

    if skipped:
        for s in skipped:
            print(f'  {C.DIM}skip  {s}{C.RESET}')
        print()

    # Group by label, preserving encounter order
    groups: dict[str, list] = OrderedDict()
    for i in issues:
        groups.setdefault(i.label, []).append(i)

    for label, group in groups.items():
        type_part, asset_part = label.split('/', 1)
        _section(f'{type_part}  /  {asset_part}')
        for i in group:
            print(_issue_line(i))
        print()

    # Summary line
    counts  = {k: 0 for k in _KIND}
    fixable = 0
    for i in issues:
        counts[i.kind] += 1
        if i._fix:
            fixable += 1

    _hr('═', bold=True)
    parts = [f'{C.BOLD}{scanned}{C.RESET} asset{"s" if scanned != 1 else ""} scanned']
    if counts['EXTRA_PREFIX']:
        n = counts['EXTRA_PREFIX']
        parts.append(f'{C.RED}✗ {n} prefix error{"s" if n != 1 else ""}{C.RESET}')
    if counts['MISSING_PREFIX']:
        n = counts['MISSING_PREFIX']
        parts.append(f'{C.YELLOW}▲ {n} missing prefix{"es" if n != 1 else ""}{C.RESET}')
    if counts['SPACE']:
        n = counts['SPACE']
        parts.append(f'{C.CYAN}~ {n} space{"s" if n != 1 else ""}{C.RESET}')
    if counts['WARNING']:
        n = counts['WARNING']
        parts.append(f'{C.DIM}· {n} warning{"s" if n != 1 else ""}{C.RESET}')
    print('  ' + '  ·  '.join(parts))
    if fixable:
        print(f'  {C.DIM}{fixable} auto-fixable{C.RESET}')
    _hr('═', bold=True)


# ── Interactive fix ───────────────────────────────────────────────────────────

def _prompt(msg: str, hint: str) -> str:
    try:
        return input(f'  {C.BOLD}{msg}{C.RESET}  {C.DIM}[{hint}]{C.RESET}  ▶  ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def fix_interactive(issues: list):
    fixable = [i for i in issues if i._fix is not None]
    if not fixable:
        return

    print()
    _hr()
    print(f'  {C.BOLD}{len(fixable)}{C.RESET} auto-fixable issue(s)')
    mode = _prompt('Fix all / review one by one / skip', 'a / r / s')
    _hr()

    if mode == 's':
        return

    ordered  = sorted(fixable, key=lambda i: len(i.path.parts))
    fix_all  = (mode == 'a')

    for issue in ordered:
        if not fix_all:
            print()
            icon, col = _KIND[issue.kind]
            color     = getattr(C, col)
            label_dim = f'{C.DIM}({issue.label}){C.RESET}'
            print(f'  {color}{icon}{C.RESET}  {issue.detail}  {label_dim}')
            ans = _prompt('Apply?', 'y / n / a=all / q=quit')
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

    if args.root:
        structure = Path(args.root).resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        cfg_path   = script_dir / 'SHOOT_BROWSER' / 'Config' / 'project_config.json'
        if not cfg_path.exists():
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
                cfg    = json.loads(cfg_path.read_text())
                custom = (cfg.get('paths') or {}).get('assets_shoot', '').strip()
                if custom:
                    return Path(custom).resolve()
            except Exception:
                pass
            structure = script_dir

    p = structure / DEFAULT_REL
    if not p.exists():
        sys.exit(f'Error: ASSETS_SHOOT not found at {p}\nUse --path to specify explicitly.')
    return p


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='ASSETS_SHOOT sanity checker')
    parser.add_argument('--path',     help='Direct path to ASSETS_SHOOT directory')
    parser.add_argument('--root',     help='Path to STRUCTURE directory (uses STRUCTURE/ASSETS_SHOOT)')
    parser.add_argument('--dry-run',  action='store_true', help='Report only, no fix prompts')
    parser.add_argument('--no-color', action='store_true', help='Disable ANSI colors')
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.off()

    root = _resolve_root(args)

    print()
    _hr('═', bold=True)
    print(f'  {C.BOLD}ASSETS_SHOOT  ·  Sanity Check{C.RESET}')
    print(f'  {C.DIM}{root}{C.RESET}')
    _hr('═', bold=True)
    print()

    issues, skipped, scanned = scan(root)

    if not issues:
        if skipped:
            for s in skipped:
                print(f'  {C.DIM}skip  {s}{C.RESET}')
            print()
        _hr('═', bold=True)
        print(f'  {C.GREEN}✓  All {scanned} assets clean — no issues found.{C.RESET}')
        _hr('═', bold=True)
        print()
        return

    report(issues, scanned, skipped)

    if not args.dry_run:
        fix_interactive(issues)

    print()


if __name__ == '__main__':
    main()
