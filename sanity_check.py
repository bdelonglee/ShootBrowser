#!/usr/bin/env python3
"""
VFX Shoot Data Sanity Check Script
Validates directory structure against template and naming conventions
"""

import os
import re
import csv
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class DirectoryInfo:
    """Information about a shoot day directory"""
    path: Path
    day: str  # JXX or PJXX
    scenes: List[str]  # List of SXX
    code: str  # 4-letter code
    description: str


@dataclass
class PrefixIssue:
    """Information about a prefix consistency issue"""
    dir_path: Path
    parent_day_path: Path
    issue_type: str  # 'missing_prefix' or 'extra_prefix'
    is_empty: bool
    relative_path: Path


@dataclass
class SceneCodeMapping:
    """Scene to Code mapping from Editorial CSV"""
    scene: str  # Scene number (not padded, e.g., "1", "15", "100")
    codes: List[str]  # List of codes for this scene


class SanityChecker:
    """Main class for validating VFX shoot directory structure"""

    # Regex patterns
    DAY_PATTERN = re.compile(r'^(J\d{2}|PJ\d{2})$')
    SCENE_PATTERN = re.compile(r'^S\d{2}$')
    CODE_PATTERN = re.compile(r'^[A-Z]{4}(_[A-Z]{4})*$')
    DIR_PATTERN = re.compile(
        r'^(J\d{2}|PJ\d{2})__(S\d{2}(?:_S\d{2})*)__([A-Z]{4}(?:_[A-Z]{4})*)__(.+)$'
    )

    # Directories to skip
    SKIP_DIRS = {'TODO__', '__RAPPORTS_SCRIPT', '__Souvenirs_Vrac', '__CALLSHEETS'}

    def __init__(self, data_path: str):
        self.data_path = Path(data_path).resolve()  # Resolve to absolute path

        # Validate data path exists and is a directory
        if not self.data_path.exists():
            raise ValueError(f"Data path does not exist: {self.data_path}")
        if not self.data_path.is_dir():
            raise ValueError(f"Data path is not a directory: {self.data_path}")

        self.template_path = self.data_path / 'J00_TEMPLATE'
        self.template_structure: Set[Path] = set()
        self.errors: List[str] = []
        self.warnings: List[str] = []

        # CSV validation data
        self.csv_path = self.data_path / 'Editorial_VFX_Code_List.csv'
        self.valid_codes: Set[str] = set()  # All valid codes from CSV
        self.scene_code_map: Dict[str, List[str]] = {}  # Scene -> List of codes
        self.csv_loaded: bool = False
        self.csv_inconsistent_dirs: List[str] = []  # Directories with CSV issues

    def parse_template(self) -> bool:
        """Parse the J00_TEMPLATE directory structure"""
        if not self.template_path.exists():
            self.errors.append(f"Template directory not found: {self.template_path}")
            return False

        print(f"📁 Parsing template: {self.template_path}")

        for root, dirs, files in os.walk(self.template_path):
            root_path = Path(root)
            rel_path = root_path.relative_to(self.template_path)

            if rel_path != Path('.'):
                self.template_structure.add(rel_path)

        print(f"   Found {len(self.template_structure)} template directories")
        return True

    def parse_directory_name(self, dir_name: str) -> DirectoryInfo | None:
        """Parse directory name following the pattern Day__SceneX_SceneY__CODE__Description"""
        match = self.DIR_PATTERN.match(dir_name)
        if not match:
            return None

        day = match.group(1)
        scenes_str = match.group(2)
        code = match.group(3)
        description = match.group(4)

        scenes = scenes_str.split('_')

        # Validate each component
        if not self.DAY_PATTERN.match(day):
            return None

        for scene in scenes:
            if not self.SCENE_PATTERN.match(scene):
                return None

        if not self.CODE_PATTERN.match(code):
            return None

        # Check description doesn't contain invalid characters
        if '__' in description or any(c in description for c in '@#$%^&*'):
            return None

        dir_path = self.data_path / dir_name
        return DirectoryInfo(dir_path, day, scenes, code, description)

    def is_directory_empty(self, dir_path: Path) -> bool:
        """
        Check if a directory is empty recursively.
        A directory is considered empty if:
        1. It contains no files (ignoring ._ hidden files), AND
        2. All subdirectories are also empty and have __ prefix
        """
        try:
            items = list(dir_path.iterdir())
        except (PermissionError, OSError):
            return True

        # Check for visible files (ignore ._ macOS metadata files)
        has_files = any(
            item.is_file() and not item.name.startswith('._')
            for item in items
        )
        if has_files:
            return False

        # Get subdirectories (ignore hidden dirs starting with .)
        subdirs = [
            item for item in items
            if item.is_dir() and not item.name.startswith('.')
        ]

        # If no subdirectories and no files, it's empty
        if not subdirs:
            return True

        # Check all subdirectories recursively
        # A directory is empty if all its subdirs are __ prefixed and empty
        for subdir in subdirs:
            # If any subdir doesn't have __ prefix, parent is not empty
            if not subdir.name.startswith('__'):
                return False
            # If any __ prefixed subdir is not empty, parent is not empty
            if not self.is_directory_empty(subdir):
                return False

        # All subdirs are __ prefixed and empty, so this dir is empty
        return True

    def check_prefix_consistency(self, dir_info: DirectoryInfo, collect_fixes: bool = False) -> Tuple[List[str], List[PrefixIssue]]:
        """Check if subdirectories follow the __ prefix rule"""
        issues = []
        fixable_issues = []

        try:
            for root, dirs, files in os.walk(dir_info.path):
                root_path = Path(root)

                # Filter out system/hidden directories to avoid
                dirs[:] = [d for d in dirs if not d.startswith('.')]

                for dir_name in dirs:
                    dir_path = root_path / dir_name
                    has_prefix = dir_name.startswith('__')
                    is_empty = self.is_directory_empty(dir_path)
                    rel_path = dir_path.relative_to(dir_info.path)

                    if is_empty and not has_prefix:
                        issues.append(
                            f"  ❌ Empty directory without __ prefix: {rel_path}"
                        )
                        if collect_fixes:
                            fixable_issues.append(PrefixIssue(
                                dir_path=dir_path,
                                parent_day_path=dir_info.path,
                                issue_type='missing_prefix',
                                is_empty=True,
                                relative_path=rel_path
                            ))
                    elif not is_empty and has_prefix:
                        issues.append(
                            f"  ⚠️  Non-empty directory with __ prefix: {rel_path}"
                        )
                        if collect_fixes:
                            fixable_issues.append(PrefixIssue(
                                dir_path=dir_path,
                                parent_day_path=dir_info.path,
                                issue_type='extra_prefix',
                                is_empty=False,
                                relative_path=rel_path
                            ))

        except PermissionError as e:
            issues.append(f"  ⚠️  Permission denied scanning directory: {e}")

        return issues, fixable_issues

    def check_template_compliance(self, dir_info: DirectoryInfo) -> List[str]:
        """Check if directory structure matches template"""
        issues = []

        # Get all subdirectories in the day directory
        day_structure = set()
        for root, dirs, files in os.walk(dir_info.path):
            root_path = Path(root)
            rel_path = root_path.relative_to(dir_info.path)

            if rel_path != Path('.'):
                day_structure.add(rel_path)

        # Find missing template directories
        missing = []
        for template_dir in self.template_structure:
            # Check if the template directory or its equivalent exists
            found = False
            template_name = template_dir.name

            # Check both with and without __ prefix
            if template_name.startswith('__'):
                alt_name = template_name[2:]
            else:
                alt_name = '__' + template_name

            for day_dir in day_structure:
                if day_dir.name in (template_name, alt_name):
                    # Check if parent path matches
                    if template_dir.parent == day_dir.parent:
                        found = True
                        break

            if not found:
                # Only report top-level missing directories
                if template_dir.parent == Path('.'):
                    missing.append(str(template_dir))

        if missing:
            issues.append(f"  ⚠️  Missing template directories: {', '.join(missing)}")

        return issues

    def get_day_directories(self) -> List[DirectoryInfo]:
        """Get all valid day directories (JXX and PJXX)"""
        day_dirs = []

        for item in self.data_path.iterdir():
            if not item.is_dir():
                continue

            # Skip special directories
            if any(skip in item.name for skip in self.SKIP_DIRS):
                continue

            # Parse directory name
            dir_info = self.parse_directory_name(item.name)
            if dir_info:
                day_dirs.append(dir_info)
            elif item.name.startswith(('J', 'PJ')) and item.name != 'J00_TEMPLATE':
                self.errors.append(f"❌ Invalid directory naming: {item.name}")

        return day_dirs

    # ========================================================================
    # CSV CODE VALIDATION FEATURE
    # ========================================================================

    def load_csv_code_list(self) -> bool:
        """Load and parse the Editorial_VFX_Code_List.csv file"""
        if not self.csv_path.exists():
            return False

        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Find the header row (contains "Scene" and "Sequence Code")
            header_row = None
            for i, row in enumerate(rows):
                if len(row) > 2 and 'Scene' in row and 'Sequence Code' in row:
                    header_row = i
                    break

            if header_row is None:
                print(f"⚠️  Could not find header row in CSV")
                return False

            # Find column indices
            scene_col = None
            code_col = None
            for i, cell in enumerate(rows[header_row]):
                if cell.strip() == 'Scene':
                    scene_col = i
                elif cell.strip() == 'Sequence Code':
                    code_col = i

            if scene_col is None or code_col is None:
                print(f"⚠️  Could not find Scene or Sequence Code columns")
                return False

            # Parse data rows
            for row in rows[header_row + 1:]:
                if len(row) <= max(scene_col, code_col):
                    continue

                scene = row[scene_col].strip()
                code = row[code_col].strip()

                # Skip empty rows
                if not scene or not code:
                    continue

                # Parse scene (remove any non-numeric characters, handle special cases like "065A")
                scene_num = scene.replace('A', '').replace('B', '').replace('?', '')
                if not scene_num:
                    continue

                # Parse codes (can be multiple separated by /)
                codes = [c.strip() for c in code.split('/')]
                codes = [c for c in codes if c and not c.endswith('?')]  # Remove empty and uncertain codes

                # Add to valid codes set
                self.valid_codes.update(codes)

                # Map scene to codes (store unpadded scene number)
                if scene_num not in self.scene_code_map:
                    self.scene_code_map[scene_num] = []
                self.scene_code_map[scene_num].extend(codes)

            # Remove duplicates from scene_code_map
            for scene in self.scene_code_map:
                self.scene_code_map[scene] = list(set(self.scene_code_map[scene]))

            self.csv_loaded = True
            return True

        except Exception as e:
            print(f"⚠️  Error loading CSV: {e}")
            return False

    def validate_codes_against_csv(self, dir_info: DirectoryInfo) -> List[str]:
        """
        Validate directory codes and scenes against CSV data.
        Returns list of issues found.
        """
        if not self.csv_loaded:
            return []

        issues = []

        # Extract individual codes from directory
        # E.g., "PONT_PISC_PLAN" becomes ["PONT", "PISC", "PLAN"]
        dir_codes = dir_info.code.split('_')

        # Check 1: Are the codes valid (present in CSV)?
        for code in dir_codes:
            if code not in self.valid_codes:
                issues.append(
                    f"  ⚠️  Code '{code}' not found in Editorial_VFX_Code_List.csv"
                )

        # Check 2: Are scene-code combinations valid?
        for scene in dir_info.scenes:
            # Convert SXX to unpadded number (S19 -> "19", S01 -> "1")
            scene_num = scene[1:].lstrip('0') or '0'

            if scene_num not in self.scene_code_map:
                issues.append(
                    f"  ⚠️  Scene {scene} ({scene_num}) not found in Editorial_VFX_Code_List.csv"
                )
                continue

            # Check if any of the directory codes are valid for this scene
            valid_codes_for_scene = self.scene_code_map[scene_num]
            matching_codes = [c for c in dir_codes if c in valid_codes_for_scene]

            if not matching_codes:
                # Show individual codes for clarity
                codes_display = ' / '.join(dir_codes) if len(dir_codes) > 1 else dir_codes[0]
                issues.append(
                    f"  ⚠️  Scene {scene} / Codes [{codes_display}] - none match expected codes in CSV"
                    f"\n      Expected codes for scene {scene}: {', '.join(valid_codes_for_scene)}"
                    f"\n      Directory codes: {', '.join(dir_codes)}"
                )

        return issues

    # ========================================================================
    # PREFIX FIX FEATURE
    # ========================================================================

    def fix_prefix_issue(self, issue: PrefixIssue) -> bool:
        """Fix a single prefix issue by renaming the directory"""
        try:
            old_path = issue.dir_path.resolve()  # Resolve to absolute path

            # Security: Ensure path is within the expected day directory
            try:
                old_path.relative_to(issue.parent_day_path)
            except ValueError:
                print(f"      ⚠️  Security: Path outside day directory: {issue.relative_path}")
                return False

            # Validate old path still exists (could have been moved by parent rename)
            if not old_path.exists():
                print(f"      ⚠️  Path no longer exists (may have been moved): {issue.relative_path}")
                return False

            # Ensure it's actually a directory (not a file or symlink)
            if not old_path.is_dir():
                print(f"      ⚠️  Not a directory: {issue.relative_path}")
                return False

            # Check for symlinks - we don't want to rename symlinks
            if old_path.is_symlink():
                print(f"      ⚠️  Skipping symlink: {issue.relative_path}")
                return False

            parent = old_path.parent
            old_name = old_path.name

            # Validate parent still exists
            if not parent.exists():
                print(f"      ⚠️  Parent directory no longer exists: {parent}")
                return False

            # Calculate new name
            if issue.issue_type == 'missing_prefix':
                new_name = '__' + old_name
            else:  # extra_prefix
                if not old_name.startswith('__'):
                    print(f"      ⚠️  Directory doesn't have __ prefix: {old_name}")
                    return False
                new_name = old_name[2:]  # Remove __ prefix

            # Validate new name is not empty
            if not new_name or new_name.startswith('.'):
                print(f"      ⚠️  Invalid new name: {new_name}")
                return False

            new_path = parent / new_name

            # Check if target already exists
            if new_path.exists():
                print(f"      ⚠️  Cannot rename: {new_name} already exists")
                return False

            # Perform the rename (atomic operation on most filesystems)
            old_path.rename(new_path)
            print(f"      ✅ Renamed: {old_name} → {new_name}")
            return True

        except PermissionError:
            print(f"      ❌ Permission denied: {issue.relative_path}")
            return False
        except OSError as e:
            print(f"      ❌ OS error renaming {issue.relative_path}: {e}")
            return False
        except Exception as e:
            print(f"      ❌ Unexpected error renaming {issue.relative_path}: {e}")
            return False

    def validate_fixes(self, issues: List[PrefixIssue]) -> Tuple[bool, List[str]]:
        """Validate that all fixes can be performed without conflicts"""
        errors = []

        # Check for duplicate target names (after renaming)
        target_paths = {}
        for issue in issues:
            old_path = issue.dir_path
            parent = old_path.parent
            old_name = old_path.name

            if issue.issue_type == 'missing_prefix':
                new_name = '__' + old_name
            else:
                new_name = old_name[2:]

            new_path = parent / new_name

            # Check if this target path conflicts with another planned rename
            if new_path in target_paths:
                errors.append(
                    f"Conflict: Both {target_paths[new_path]} and {issue.relative_path} "
                    f"would rename to {new_path.name}"
                )
            else:
                target_paths[new_path] = issue.relative_path

            # Check if target already exists in filesystem
            if new_path.exists():
                errors.append(
                    f"{issue.relative_path}: target {new_name} already exists"
                )

        return (len(errors) == 0, errors)

    def ask_to_fix_day(self, day_name: str, issues: List[PrefixIssue]) -> bool:
        """Ask user if they want to fix issues for a specific day"""
        if not issues:
            return False

        print(f"\n  Found {len(issues)} fixable prefix issue(s) in {day_name}")

        # Validate fixes before asking
        valid, validation_errors = self.validate_fixes(issues)
        if not valid:
            print(f"  ⚠️  Cannot fix automatically due to conflicts:")
            for error in validation_errors:
                print(f"      - {error}")
            return False

        print(f"  Do you want to fix them? (y/n): ", end='', flush=True)

        try:
            response = input().strip().lower()
            return response in ('y', 'yes')
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    def run(self, interactive: bool = False, validate_csv: bool = True) -> bool:
        """Run all sanity checks"""
        print("\n" + "="*70)
        print("🎬 VFX SHOOT DATA SANITY CHECK")
        if interactive:
            print("(Interactive Fix Mode)")
        print("="*70 + "\n")

        # Check write permissions if in interactive mode
        if interactive:
            if not os.access(self.data_path, os.W_OK):
                print(f"❌ Error: No write permission for {self.data_path}")
                print("   Cannot use --fix mode without write access\n")
                return False

        # Parse template
        if not self.parse_template():
            return False

        # Load CSV code list if validation requested
        csv_validation_enabled = False
        if validate_csv:
            print(f"\n📊 Loading Editorial VFX Code List...")
            if self.load_csv_code_list():
                print(f"   ✅ Loaded {len(self.valid_codes)} codes for {len(self.scene_code_map)} scenes")
                csv_validation_enabled = True
            else:
                print(f"   ⚠️  CSV file not found or could not be loaded")
                print(f"   Skipping CSV validation")

        # Get all day directories
        print(f"\n📂 Scanning day directories...")
        day_dirs = self.get_day_directories()
        print(f"   Found {len(day_dirs)} day directories\n")

        # Check each day directory
        for dir_info in sorted(day_dirs, key=lambda x: x.path.name):
            print(f"\n📋 Checking: {dir_info.path.name}")

            # Check template compliance
            compliance_issues = self.check_template_compliance(dir_info)
            if compliance_issues:
                self.warnings.extend(compliance_issues)
                for issue in compliance_issues:
                    print(issue)

            # Check prefix consistency
            prefix_issues, fixable_issues = self.check_prefix_consistency(dir_info, collect_fixes=interactive)
            if prefix_issues:
                self.errors.extend(prefix_issues)
                for issue in prefix_issues:
                    print(issue)

            # Check CSV code validation (separate feature)
            csv_issues = []
            if csv_validation_enabled:
                csv_issues = self.validate_codes_against_csv(dir_info)
                if csv_issues:
                    self.warnings.extend(csv_issues)
                    self.csv_inconsistent_dirs.append(dir_info.path.name)
                    for issue in csv_issues:
                        print(issue)

            # Interactive fix mode
            if interactive and fixable_issues:
                try:
                    if self.ask_to_fix_day(dir_info.path.name, fixable_issues):
                        # Sort by depth (deepest first) to fix children before parents
                        # This prevents path errors when renaming parent directories
                        sorted_issues = sorted(
                            fixable_issues,
                            key=lambda x: len(x.relative_path.parts),
                            reverse=True
                        )

                        fixed_count = 0
                        for issue in sorted_issues:
                            if self.fix_prefix_issue(issue):
                                fixed_count += 1

                        if fixed_count > 0:
                            print(f"\n  ✅ Fixed {fixed_count}/{len(fixable_issues)} issue(s)")
                        else:
                            print(f"\n  ⚠️  No issues could be fixed (see errors above)")
                    else:
                        print("  ⏭️  Skipped fixes")
                except KeyboardInterrupt:
                    print("\n\n⚠️  Fix process interrupted by user")
                    print("Some directories may have been renamed. Run again to check status.\n")
                    raise

            if not compliance_issues and not prefix_issues and not csv_issues:
                print("  ✅ All checks passed")

        # Print summary
        print("\n" + "="*70)
        print("📊 SUMMARY")
        print("="*70)
        print(f"Total directories checked: {len(day_dirs)}")
        print(f"Errors: {len(self.errors)}")
        print(f"Warnings: {len(self.warnings)}")

        if self.errors:
            print("\n🔴 ERRORS FOUND:")
            for error in self.errors:
                if not error.startswith((' ', '\t')):
                    print(error)

        if self.warnings:
            print("\n🟡 WARNINGS:")
            for warning in self.warnings:
                if not warning.startswith((' ', '\t')):
                    print(warning)

        if self.csv_inconsistent_dirs:
            print("\n📋 DIRECTORIES WITH CSV INCONSISTENCIES:")
            for dir_name in self.csv_inconsistent_dirs:
                print(f"   - {dir_name}")

        if not self.errors and not self.warnings:
            print("\n✅ All checks passed!")

        print("="*70 + "\n")

        return len(self.errors) == 0


def main():
    """Main entry point"""
    import sys
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='VFX Shoot Data Sanity Check - Validate directory structure and naming conventions'
    )
    parser.add_argument(
        'data_path',
        nargs='?',
        default="/Volumes/MACGUFF001/POSEIDON/DATA_rename",
        help='Path to the DATA_rename directory'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Interactive mode: ask to fix prefix inconsistencies for each day'
    )
    parser.add_argument(
        '--no-csv',
        action='store_true',
        help='Disable CSV code validation (skip Editorial_VFX_Code_List.csv checks)'
    )

    args = parser.parse_args()

    try:
        checker = SanityChecker(args.data_path)
        success = checker.run(interactive=args.fix, validate_csv=not args.no_csv)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user")
        sys.exit(130)  # Standard exit code for SIGINT

    except ValueError as e:
        print(f"\n❌ Error: {e}\n")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
