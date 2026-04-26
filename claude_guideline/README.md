# VFX Shoot Data Management Scripts

Python scripts for managing and browsing VFX shoot data collected during movie production.

## Overview

These scripts help maintain and navigate a structured directory system for VFX shoot data following the pattern:
```
Day__SceneX_SceneY__CODE__Description
```

## Scripts

### 1. `sanity_check.py` - Directory Structure Validator

Validates that your shoot data directories follow the correct structure and naming conventions.

#### Features
- **Template Parsing**: Reads the J00_TEMPLATE directory structure
- **Naming Validation**: Ensures directories follow the pattern `JXX__SXX__CODE__Description`
- **Template Compliance**: Checks that all day directories match the template structure
- **Prefix Consistency**: Validates the `__` prefix rule:
  - Empty directories MUST have `__` prefix
  - Non-empty directories should NOT have `__` prefix (flagged as warning)
- **Interactive Fix Mode**: Automatically fix prefix inconsistencies with user approval

#### Usage
```bash
# Read-only mode: Check for issues without making changes
python3 sanity_check.py

# Interactive fix mode: Ask to fix issues for each day
python3 sanity_check.py --fix

# Specify custom path
python3 sanity_check.py /path/to/DATA_rename

# Custom path with fix mode
python3 sanity_check.py /path/to/DATA_rename --fix

# Show help
python3 sanity_check.py --help
```

#### Interactive Fix Mode

When using the `--fix` flag, the script will:
1. Check all directories as normal
2. For each day with prefix issues, ask: "Do you want to fix them? (y/n)"
3. If you answer 'y':
   - Automatically rename directories to fix prefix issues
   - Empty directories get `__` prefix added
   - Non-empty directories get `__` prefix removed
   - Shows what was renamed and counts fixed issues
4. If you answer 'n':
   - Skips that day and continues to the next

See `INTERACTIVE_MODE_DEMO.md` for detailed examples.

#### Safety Features

The `--fix` mode includes comprehensive safety protections:
- ✅ **Path validation** - Ensures all paths exist and are valid before renaming
- ✅ **Permission checks** - Verifies write access before starting
- ✅ **Conflict detection** - Pre-validates all renames for conflicts
- ✅ **Symlink protection** - Skips symbolic links
- ✅ **Correct ordering** - Renames children before parents to avoid path errors
- ✅ **Per-day confirmation** - User approves each day individually
- ✅ **Graceful interruption** - Handles Ctrl+C cleanly
- ✅ **Read-only by default** - Requires explicit `--fix` flag to modify
- ✅ **Atomic operations** - Rename succeeds or fails completely
- ✅ **Path traversal protection** - Can't rename outside expected directories

See `SAFETY_FEATURES.md` for complete documentation of all safety measures.

#### Output
- ✅ Success messages for compliant directories
- ❌ Errors for structural violations
- ⚠️  Warnings for potential issues
- Summary report with total errors and warnings

#### Example Output
```
======================================================================
🎬 VFX SHOOT DATA SANITY CHECK
======================================================================

📁 Parsing template: /Volumes/MACGUFF001/POSEIDON/DATA_rename/J00_TEMPLATE
   Found 21 template directories

📂 Scanning day directories...
   Found 19 day directories

📋 Checking: J01__S19__PORT__Montparnasse_Exterieur
  ❌ Empty directory without __ prefix: 20_HDR/Theta
  ❌ Empty directory without __ prefix: 20_HDR/Theta_Underwater

📋 Checking: PJ03__S80__EIFF__Tour_Eiffel_Cachette
  ✅ All checks passed

======================================================================
📊 SUMMARY
======================================================================
Total directories checked: 19
Errors: 15
Warnings: 3
```

---

### 2. `generate_html.py` - Interactive Data Browser

Generates a beautiful, interactive HTML page to browse shoot data organized by days, scenes, or codes.

#### Features
- **Three View Modes**:
  - 📅 **By Days**: Sort entries by shoot day (JXX/PJXX)
  - 🎞️ **By Scenes**: Group entries by scene number (SXX)
  - 🏷️ **By Codes**: Organize by 4-letter codes

- **Rich Information Display**:
  - Directory name and description
  - Day, scene, and code badges
  - Data status (has files or empty)
  - List of subdirectories

- **Interactive UI**:
  - One-click mode switching
  - Real-time statistics
  - Hover effects and smooth transitions
  - Responsive design for all screen sizes

#### Usage
```bash
# Use default path, output to vfx_shoot_browser.html
python3 generate_html.py

# Specify custom data path
python3 generate_html.py /path/to/DATA_rename

# Specify custom data path and output file
python3 generate_html.py /path/to/DATA_rename custom_output.html
```

#### Output
Creates an HTML file that can be opened in any web browser. No server required - it's a self-contained static page.

#### Screenshots
The generated page features:
- Clean, modern interface with blue gradient theme
- Color-coded badges for different information types
- Expandable directory listings
- Statistics dashboard

---

## Directory Structure Rules

### Naming Pattern
```
Day__SceneX_SceneY__CODE__Description
```

**Components**:
- **Day**: `JXX` (jour) or `PJXX` (plate jour)
  - Examples: `J01`, `J08`, `PJ02`, `PJ09`

- **Scenes**: `SXX` format, single or multiple separated by `_`
  - Examples: `S19`, `S37_S38`, `S62_S75_S80`

- **Code**: 4 uppercase letters, can be multiple separated by `_`
  - Examples: `PORT`, `MONT`, `RIDE_DAME`, `OPEN_RITZ`

- **Description**: Free text, no `__` or special characters like `@#$%^`
  - Examples: `Montparnasse_Exterieur`, `Notre_Dame`, `Metro_Louvre-Rivoli`

### Special Directories

**Skip these**:
- `TODO__*` - Work in progress, not yet organized
- `__RAPPORTS_SCRIPT` - Script reports
- `__Souvenirs_Vrac` - Miscellaneous souvenirs
- `__CALLSHEETS` - Feuilles de service (call sheets)
- `J00_TEMPLATE` - Template structure for all day directories

### Subdirectory Prefix Rules

Within day directories:
- **Empty directories**: MUST start with `__`
  - Examples: `__00_Database`, `__30_Photog_Polycam`, `__HDR/__Fisheye`

- **Non-empty directories**: Should NOT start with `__`
  - Examples: `60_Temoin_Photos` (if it contains files)

This rule helps quickly identify which directories contain data.

## Template Structure (J00_TEMPLATE)

Standard subdirectory structure:
```
__00_Database
__10_Infos
__100_Souvenirs
__20_HDR
    __Fisheye
    __Theta
    __Theta_Underwater
__30_Photog_Polycam
__31_Photog_Scale
__32_Photog_Photos
__33_Lidar
__40_Photos
__50_Videos
    __10_Sony
    __20_Insta360_raw
__60_Temoin_Photos
__70_Temoin_Videos
    __Insta360
    __Iphone
__80_References_Preshoot
__90_References
```

Day directories should follow this structure but can:
- Add additional subdirectories
- Remove the `__` prefix when directories contain files

## Common Issues Found by Sanity Check

1. **Empty directories without `__` prefix** ✨ *Auto-fixable with `--fix`*
   - Fix: Rename `20_HDR` to `__20_HDR` if empty
   - Or run: `python3 sanity_check.py --fix` and answer 'y'

2. **Non-empty directories with `__` prefix** ✨ *Auto-fixable with `--fix`*
   - Fix: Rename `__70_Temoin_Videos` to `70_Temoin_Videos` if it contains files
   - Or run: `python3 sanity_check.py --fix` and answer 'y'

3. **Invalid directory naming** ⚠️ *Manual fix required*
   - Fix: Ensure pattern matches `JXX__SXX__CODE__Description`
   - Check CODE is 4 uppercase letters only

4. **Missing template directories** ⚠️ *Manual fix required*
   - Fix: Add missing directories from J00_TEMPLATE

5. **Nested empty directories without prefix** ✨ *Auto-fixable with `--fix`*
   - Fix: Rename subdirectories like `Theta` to `__Theta` if empty
   - Or run: `python3 sanity_check.py --fix` and answer 'y'

## Requirements

- Python 3.7+
- No external dependencies (uses only standard library)

## Tips

1. **Run sanity check regularly** after collecting new data
2. **Use `--fix` mode** to quickly fix prefix issues with approval prompts
3. **Fix errors before warnings** - errors indicate structural problems
4. **Use the HTML browser** to quickly navigate and verify your data organization
5. **Keep J00_TEMPLATE updated** if you change the standard structure
6. **Bookmark the generated HTML** for quick access during post-production
7. **Backup before fixing** - Consider backing up data before using `--fix` mode

## Example Workflow

```bash
# 1. After collecting shoot data, run sanity check (read-only)
python3 sanity_check.py

# 2. Fix prefix issues interactively (optional but recommended)
python3 sanity_check.py --fix
# This will ask you day by day if you want to fix issues
# Answer 'y' to fix, 'n' to skip

# 3. Fix any remaining errors manually (if needed)
# - Invalid directory naming
# - Missing template directories

# 4. Verify all issues are resolved
python3 sanity_check.py

# 5. Generate HTML browser
python3 generate_html.py

# 6. Open vfx_shoot_browser.html in your browser
open vfx_shoot_browser.html  # macOS
# or
xdg-open vfx_shoot_browser.html  # Linux
# or just double-click the file
```

## License

Internal tool for VFX production use.
