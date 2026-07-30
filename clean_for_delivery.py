#!/usr/bin/env python3
"""
clean_for_delivery.py — Prepare a POSEIDON structure copy for VFX vendor delivery.

Rules applied to every block (DATA/*) and asset (ASSETS_SHOOT/*/*):

  __-prefixed dir, no real content  →  REMOVE   (empty template placeholder)
  __-prefixed dir, has real content →  RENAME   (strip __ prefix; parent also renamed
                                                  if it is itself __-prefixed)
  Any dir named 'history'           →  DELETE   (version archives)

"Real content" = any file (excluding macOS ._* companions), or any non-__-prefixed subdir
(excluding 'history', which is scheduled for deletion).

Dry-run is the DEFAULT — nothing changes unless you pass --apply.

Usage:
    python clean_for_delivery.py <root>           # dry-run (safe)
    python clean_for_delivery.py <root> --apply   # show report, confirm, then execute
"""

import argparse
import shutil
import sys
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_dunder(name: str) -> bool:
    return name.startswith('__')


def _is_real_file(p: Path) -> bool:
    return p.is_file() and not p.name.startswith('._')


def _file_count(path: Path) -> int:
    try:
        return sum(1 for p in path.rglob('*') if _is_real_file(p))
    except Exception:
        return 0


def _stripped(path: Path) -> Path:
    """Return path with __ prefix removed from the final component."""
    return path.with_name(path.name.lstrip('_'))


# ── Recursive analysis of a __-prefixed directory ────────────────────────────

def _analyze(path: Path) -> dict:
    """
    Classify one __-prefixed directory.

    Returns:
      action   : 'remove' | 'rename'
      renames  : list of (from_path, to_path) — children FIRST, then self
                 (only populated when action == 'rename')
      removes  : list of Path — empty __ children inside a to-be-renamed parent
                 (only populated when action == 'rename'; handled by rmtree when action == 'remove')
      histories: list of Path — history dirs found inside
    """
    renames:   list[tuple[Path, Path]] = []
    removes:   list[Path]              = []
    histories: list[Path]              = []
    has_real = False

    try:
        children = sorted(path.iterdir(), key=lambda p: p.name)
    except PermissionError:
        return dict(action='remove', renames=[], removes=[], histories=[])

    for child in children:
        if child.is_symlink() or _is_real_file(child):
            has_real = True
            continue
        if not child.is_dir():
            continue

        if child.name == 'history':
            histories.append(child)
            continue

        if _is_dunder(child.name):
            sub = _analyze(child)
            histories.extend(sub['histories'])
            if sub['action'] == 'rename':
                has_real = True
                renames.extend(sub['renames'])
                removes.extend(sub['removes'])
            else:
                # Empty child: if we end up renaming self, this child needs explicit removal
                removes.append(child)
        else:
            has_real = True  # regular non-__ subdir

    if has_real:
        renames.append((path, _stripped(path)))
        return dict(action='rename', renames=renames, removes=removes, histories=histories)
    else:
        # Entire subtree is empty / only empty __ dirs — remove the whole thing
        return dict(action='remove', renames=[], removes=[], histories=histories)


def _find_histories_in_regular(path: Path) -> list[Path]:
    """Find 'history' dirs inside regular (non-__-prefixed) dirs only."""
    result = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if _is_dunder(child.name):
                continue  # handled by _analyze
            if child.name == 'history':
                result.append(child)
            else:
                result.extend(_find_histories_in_regular(child))
    except PermissionError:
        pass
    return result


# ── Per-container (block / asset) scan ───────────────────────────────────────

class ContainerReport:
    def __init__(self, path: Path):
        self.path      = path
        self.renames:  list[tuple[Path, Path]] = []  # (from, to) children-first
        self.removes:  list[Path]              = []  # top-level empty __ dirs, + nested empties inside renames
        self.histories: list[Path]             = []

    @property
    def is_clean(self) -> bool:
        return not self.renames and not self.removes and not self.histories


def scan_container(root: Path) -> ContainerReport:
    report = ContainerReport(root)
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name)
    except PermissionError:
        return report

    for child in children:
        if not child.is_dir():
            continue
        if child.name == 'history':
            report.histories.append(child)
            continue
        if _is_dunder(child.name):
            res = _analyze(child)
            report.histories.extend(res['histories'])
            if res['action'] == 'rename':
                report.renames.extend(res['renames'])
                report.removes.extend(res['removes'])
            else:
                report.removes.append(child)
        else:
            report.histories.extend(_find_histories_in_regular(child))

    return report


# ── Root scanner ──────────────────────────────────────────────────────────────

def scan_all(root: Path) -> list[ContainerReport]:
    reports = []

    def _scan(path: Path, depth: int) -> None:
        if depth == 0:
            r = scan_container(path)
            if not r.is_clean:
                reports.append(r)
            return
        try:
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                if child.is_dir() and not _is_dunder(child.name):
                    _scan(child, depth - 1)
        except PermissionError:
            pass

    data   = root / 'DATA'
    assets = root / 'ASSETS_SHOOT'
    if data.is_dir():
        _scan(data, depth=1)      # DATA/block/
    if assets.is_dir():
        _scan(assets, depth=2)    # ASSETS_SHOOT/type/asset/

    return reports


# ── Display ───────────────────────────────────────────────────────────────────

def print_report(reports: list[ContainerReport], root: Path) -> tuple[int, int, int]:
    """Print grouped report; return (n_renames, n_removes, n_histories)."""
    n_renames = n_removes = n_histories = 0

    for report in reports:
        rel = report.path.relative_to(root)
        print(f"  {rel}")

        # Build a combined, sorted-by-path list of everything to display
        actions: list[tuple[Path, str, str]] = []  # (path, tag, detail)

        # Renames — display parent first (reverse of execution order)
        for from_p, to_p in sorted(report.renames, key=lambda r: len(r[0].parts)):
            n = _file_count(from_p)
            detail = f"→ {to_p.name}" + (f"  ({n} file{'s' if n != 1 else ''})" if n else "")
            actions.append((from_p, 'RENAME', detail))

        # Removes
        for p in sorted(report.removes, key=lambda p: len(p.parts)):
            actions.append((p, 'REMOVE', '(empty)'))

        # Histories
        for p in sorted(report.histories, key=lambda p: len(p.parts)):
            n = _file_count(p)
            actions.append((p, 'DELETE', f"history  ({n} file{'s' if n != 1 else ''})"))

        base_depth = len(report.path.parts)
        for path, tag, detail in sorted(actions, key=lambda a: (len(a[0].parts), a[0])):
            depth  = len(path.parts) - base_depth
            indent = '    ' + '  ' * (depth - 1)
            rel_p  = path.relative_to(report.path)
            print(f"{indent}[{tag}]  {rel_p}  {detail}")

        n_renames   += len(report.renames)
        n_removes   += len(report.removes)
        n_histories += len(report.histories)
        print()

    return n_renames, n_removes, n_histories


# ── Execution ─────────────────────────────────────────────────────────────────

def apply_report(report: ContainerReport) -> int:
    errors = 0

    def _rm(path: Path, label: str) -> bool:
        try:
            shutil.rmtree(path)
            print(f"    Deleted  {label}")
            return True
        except Exception as exc:
            print(f"    ERROR    {label}: {exc}", file=sys.stderr)
            return False

    def _mv(src: Path, dst: Path) -> bool:
        try:
            src.rename(dst)
            print(f"    Renamed  {src.name}  →  {dst.name}")
            return True
        except Exception as exc:
            print(f"    ERROR    {src.name} → {dst.name}: {exc}", file=sys.stderr)
            return False

    # 1. Delete history dirs
    for h in report.histories:
        if not _rm(h, str(h.relative_to(report.path))):
            errors += 1

    # 2. Remove empty __ dirs (shallowest first — rmtree handles subtrees)
    for p in sorted(report.removes, key=lambda p: len(p.parts)):
        if not p.exists():
            continue
        if not _rm(p, str(p.relative_to(report.path))):
            errors += 1

    # 3. Rename __ dirs — children first (deepest first)
    for from_p, to_p in sorted(report.renames, key=lambda r: -len(r[0].parts)):
        if not from_p.exists():
            print(f"    SKIP     {from_p.name} (already moved)", file=sys.stderr)
            continue
        if to_p.exists():
            print(f"    SKIP     {from_p.name} (target {to_p.name} already exists)", file=sys.stderr)
            errors += 1
            continue
        if not _mv(from_p, to_p):
            errors += 1

    return errors


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Clean a POSEIDON structure copy for VFX vendor delivery.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('root', help='Root of the copy to clean (must contain DATA/ and/or ASSETS_SHOOT/)')
    ap.add_argument('--apply', action='store_true',
                    help='Execute changes after confirmation (default: dry-run only)')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"ERROR: {root} is not a directory.")
    if not (root / 'DATA').is_dir() and not (root / 'ASSETS_SHOOT').is_dir():
        sys.exit(f"ERROR: {root} contains neither DATA/ nor ASSETS_SHOOT/.")

    mode = 'APPLY' if args.apply else 'DRY RUN'
    print(f"[{mode}] Scanning {root} …\n")

    reports = scan_all(root)

    if not reports:
        print("Nothing to do — structure is already clean.")
        return

    # Group by section for display
    data_reports   = [r for r in reports if 'DATA' in r.path.parts]
    assets_reports = [r for r in reports if 'ASSETS_SHOOT' in r.path.parts]

    if data_reports:
        print("── DATA " + '─' * 63)
        nr, nrm, nh = print_report(data_reports, root)
    else:
        nr = nrm = nh = 0

    if assets_reports:
        print("── ASSETS_SHOOT " + '─' * 54)
        ar, arm, ah = print_report(assets_reports, root)
        nr += ar; nrm += arm; nh += ah

    total = nr + nrm + nh
    print("── Summary " + '─' * 59)
    print(f"  Containers with changes : {len(reports)}")
    print(f"  Renames  (__ → name)    : {nr}")
    print(f"  Removes  (empty __)     : {nrm}")
    print(f"  Deletes  (history/)     : {nh}")
    print(f"  Total actions           : {total}")
    print()

    if not args.apply:
        print("[DRY RUN] Nothing was changed. Re-run with --apply to execute.")
        return

    # Confirm
    ans = input(f"Apply {total} action(s) to {root}? [y/N] ").strip().lower()
    if ans != 'y':
        print("Aborted.")
        return

    print()
    total_errors = 0
    for report in reports:
        rel = report.path.relative_to(root)
        print(f"  {rel}")
        total_errors += apply_report(report)
        print()

    if total_errors:
        print(f"Done with {total_errors} error(s). See output above.")
        sys.exit(1)
    else:
        print(f"Done. {total} action(s) applied.")


if __name__ == '__main__':
    main()
