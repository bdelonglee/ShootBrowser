# ShootBrowser

VFX Shoot Data Management and Browser - Python tools for organizing and browsing VFX shoot data collected during movie production.

## Quick Start

### 1. Sanity Check - Validate Directory Structure

```bash
# Check for issues (read-only, safe)
python3 sanity_check.py

# Interactive fix mode - ask to fix issues for each day
python3 sanity_check.py --fix
```

### 2. Generate HTML Browser

```bash
# Generate interactive HTML page
python3 generate_html.py

# Open in browser
open vfx_shoot_browser.html
```

## Features

### 📋 `sanity_check.py` - Directory Structure Validator
- Validates naming patterns: `JXX__SXX__CODE__Description`
- Checks template compliance
- Validates `__` prefix rules (empty dirs must have `__`, non-empty should not)
- **Interactive fix mode** with safety protections
- Per-day approval for automated fixes

### 🌐 `generate_html.py` - Interactive Data Browser
- Beautiful HTML interface with 3 sorting modes:
  - 📅 By Days (JXX/PJXX)
  - 🎞️ By Scenes (SXX)
  - 🏷️ By Codes (4-letter codes)
- Self-contained, works offline
- No dependencies required

## Directory Structure

```
Day__SceneX_SceneY__CODE__Description
```

**Example**: `J01__S19__PORT__Montparnasse_Exterieur`
- **Day**: `J01` (jour 1)
- **Scene**: `S19` (scene 19)
- **Code**: `PORT` (4 uppercase letters)
- **Description**: `Montparnasse_Exterieur`

## Documentation

Full documentation in [`claude_guideline/`](claude_guideline/):
- **[README.md](claude_guideline/README.md)** - Complete documentation
- **[INTERACTIVE_MODE_DEMO.md](claude_guideline/INTERACTIVE_MODE_DEMO.md)** - Interactive fix examples
- **[SAFETY_FEATURES.md](claude_guideline/SAFETY_FEATURES.md)** - Safety documentation

## Requirements

- Python 3.7+
- No external dependencies (standard library only)

## Safety Features

The `--fix` mode includes comprehensive safety protections:
- ✅ Path validation and permission checks
- ✅ Conflict detection and resolution
- ✅ Symlink protection
- ✅ Per-day user confirmation
- ✅ Graceful error handling
- ✅ Read-only by default

See [SAFETY_FEATURES.md](claude_guideline/SAFETY_FEATURES.md) for details.

## Example Workflow

```bash
# 1. Check for issues
python3 sanity_check.py

# 2. Fix them interactively
python3 sanity_check.py --fix

# 3. Generate HTML browser
python3 generate_html.py

# 4. Open in browser
open vfx_shoot_browser.html
```

## License

Internal VFX production tool.

## Author

Created for POSEIDON VFX production.
