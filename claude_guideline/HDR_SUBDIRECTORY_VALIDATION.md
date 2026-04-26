# HDR Subdirectory Validation Feature

## Overview

This feature validates and fixes subdirectory naming within HDR directories (`__20_HDR` or `20_HDR`). Subdirectories inside `Fisheye`, `Theta`, and `Theta_Underwater` must follow a specific naming pattern.

## Required Pattern

Subdirectories must start with: `SXX__TYPE__` or `GLOBAL__TYPE__`

Where:
- **SXX** = Scene code from parent day directory (e.g., `S01`, `S37`, `S62`)
- **GLOBAL** = For HDR captures that can't be assigned to a specific scene
- **TYPE** = Automatically determined by parent directory:
  - **F** for subdirectories in `Fisheye` (or `__Fisheye`)
  - **T** for subdirectories in `Theta` (or `__Theta`)
  - **U** for subdirectories in `Theta_Underwater` (or `__Theta_Underwater`)

### Examples

**Valid names**:
```
20_HDR/Fisheye/S01__F__slate_P1-2
20_HDR/Theta/S37__T__position_01
20_HDR/Theta_Underwater/S62__U__test_shot
```

**Invalid names** (missing pattern):
```
20_HDR/Fisheye/slate_P1-2           ❌ Missing SXX__F__
20_HDR/Theta/S37__position_01       ❌ Missing type code
20_HDR/Theta/position_01            ❌ Missing scene and type
```

## Directory Structure

The feature checks these specific paths:

```
Day_Directory/
└── 20_HDR/ (or __20_HDR/)
    ├── Fisheye/ (or __Fisheye/)
    │   └── S01__F__* (required pattern)
    ├── Theta/ (or __Theta/)
    │   └── S01__T__* (required pattern)
    └── Theta_Underwater/ (or __Theta_Underwater/)
        └── S01__U__* (required pattern)
```

**Note**: HDR parent directories can have `__` prefix or not, depending on whether they contain data.

## Validation

### Detection

The script automatically:
1. Finds HDR directories (`20_HDR` or `__20_HDR`)
2. Checks each of the three subdirectory types (with or without `__` prefix)
3. Validates all subdirectories inside follow the pattern
4. Verifies scene codes match parent day directory scenes

### Example Output

```bash
📋 Checking: PJ04__S01_S02__CAST_RITZ__Regina_Exterieur
  ❌ HDR subdirectory doesn't follow pattern SXX__F__: 20_HDR/Fisheye/slate_P1-2
  ❌ HDR subdirectory doesn't follow pattern SXX__F__: 20_HDR/Fisheye/slate_P1-2B
  ❌ HDR subdirectory doesn't follow pattern SXX__F__: 20_HDR/Fisheye/slate_P2-1
```

## Interactive Fix Mode

When running with `--fix`, the script offers to rename HDR subdirectories interactively.

### Fix Options

For each invalid subdirectory, you get options based on parent scenes:

**Example**: Parent is `PJ04__S01_S02__CAST_RITZ__Regina_Exterieur`

```
📁 Fix HDR subdirectory: 20_HDR/Fisheye/slate_P1-2
   Current name: slate_P1-2
   Location: Fisheye
   Required pattern: SXX__F__*

   Available scenes from parent directory:
     1. Add S01__ → S01__F__slate_P1-2
     2. Add S02__ → S02__F__slate_P1-2
     3. Custom prefix (you enter)
     0. Skip

   Choose option (0-3):
```

### Option 1 or 2: Use Scene from Parent

Simply select the scene number that corresponds to this HDR capture.

**Result**: `slate_P1-2` → `S01__F__slate_P1-2`

### Option 3: Custom Prefix

Enter your own prefix if the scene isn't in the parent list.

**Prompts**:
```
Enter custom prefix (must be SXX__F__ format)
Valid scenes: S01, S02
Example: S37__F__
Prefix: S05__F__
```

**Validation**:
- Automatically adds trailing `__` if missing
- Checks if pattern is valid (`SXX__TYPE__`)
- Warns if scene not in parent directory
- Warns if type code doesn't match expected
- **Asks for confirmation** if pattern is non-standard

**Example dialogue**:
```
Prefix: S05
Added trailing '__': S05__

⚠️  Invalid pattern. Expected: SXX__F__
Use anyway? (y/n): n

Prefix: S05__F__
⚠️  Scene 'S05' not in parent directory scenes: S01, S02
Use anyway? (y/n): y
✅ Renamed: slate_P1-2 → S05__F__slate_P1-2
```

### Safety Features

1. **Scene validation**: Checks scene exists in parent directory
2. **Type validation**: Checks type code matches HDR directory (F/T/U)
3. **Pattern validation**: Ensures format is correct
4. **Partial prefix detection**: Automatically removes `SXX__` prefix to avoid duplication
5. **Confirmation prompts**: Asks before using non-standard patterns
6. **User control**: Can skip any rename
7. **No batch operations**: Each subdirectory is handled individually

## Execution Order

**Important**: HDR subdirectories are fixed **before** prefix fixes.

This ensures:
- Parent directory name stays stable during HDR fixes
- No path errors from parent renames
- Clean, predictable execution flow

```
For each day directory:
  1. Check all issues
  2. Fix HDR subdirectories (if --fix)
  3. Fix prefix issues (if --fix)
```

## Usage

### Check Only (Read-Only)

```bash
python3 sanity_check.py

# Output shows HDR issues:
# ❌ HDR subdirectory doesn't follow pattern SXX__F__: 20_HDR/Fisheye/slate_P1-2
```

### Interactive Fix Mode

```bash
python3 sanity_check.py --fix

# For each day with HDR issues:
# Found 7 HDR subdirectory issue(s)
# Fix HDR subdirectories? (y/n): y
# [Interactive prompts for each subdirectory]
```

### Skip HDR Fixes

If you want to fix other issues but skip HDR:
```bash
python3 sanity_check.py --fix

# When prompted:
# Fix HDR subdirectories? (y/n): n
# ⏭️  Skipped HDR fixes
```

## Common Scenarios

### Scenario 1: Simple Scene Assignment

Directory has scenes S01 and S02, HDR captured for scene 1:

```
slate_P1-2 → Option 1 → S01__F__slate_P1-2
```

### Scenario 2: Multiple Scenes

Directory has S37 and S38, need to add both:

```
test_shot → Option 1 → S37__F__test_shot
another_shot → Option 2 → S38__F__another_shot
```

### Scenario 3: Custom Scene

HDR captured for a scene not in parent directory:

```
Current: slate_reference
Parent scenes: S01, S02
Action: Option 3, enter S99__F__
Result: S99__F__slate_reference (with confirmation)
```

### Scenario 4: Partial Prefix Detected

**The script automatically detects and handles partial prefixes!**

When a directory already has `SXX__` prefix (but missing type code):

```
Current: S19__toit_montparnasse_nuit
Detected partial prefix, base name: toit_montparnasse_nuit
Pattern check: Missing F

Options shown (using base name):
  1. Add S19__ → S19__F__toit_montparnasse_nuit ✅
  2. Add S20__ → S20__F__toit_montparnasse_nuit ✅

No duplication! The partial S19__ prefix is automatically removed.
```

**Without this feature**, options would incorrectly show:
```
❌ S19__F__S19__toit_montparnasse_nuit (wrong - duplication!)
```

## Type Codes Reference

| HDR Directory | Type Code | Example Result |
|--------------|-----------|----------------|
| `Fisheye` or `__Fisheye` | F | `S01__F__capture` |
| `Theta` or `__Theta` | T | `S37__T__capture` |
| `Theta_Underwater` or `__Theta_Underwater` | U | `S62__U__capture` |

## Validation Rules

The script validates:

1. **Pattern format**: `SXX__TYPE__*` where SXX is S + 2 digits
2. **Scene exists**: SXX must be in parent directory's scene list
3. **Type matches**: TYPE must match HDR directory (F/T/U)
4. **No duplicates**: Checks if target name already exists

### Valid Scene Codes

From parent: `PJ03__S37_S38__RIDE__Test`
- Valid: S37, S38
- Invalid: S01, S99, S100 (not in parent)

## Examples from Real Data

### Before Fix

```
PJ04__S01_S02__CAST_RITZ__Regina_Exterieur/
└── 20_HDR/
    └── Fisheye/
        ├── slate_P1-2          ❌
        ├── slate_P1-2B         ❌
        ├── slate_P2-1          ❌
        └── slate_P2-2_parvis   ❌
```

### After Fix

```
PJ04__S01_S02__CAST_RITZ__Regina_Exterieur/
└── 20_HDR/
    └── Fisheye/
        ├── S01__F__slate_P1-2         ✅
        ├── S01__F__slate_P1-2B        ✅
        ├── S02__F__slate_P2-1         ✅
        └── S02__F__slate_P2-2_parvis  ✅
```

## Error Messages

### Missing Pattern
```
❌ HDR subdirectory doesn't follow pattern SXX__F__: 20_HDR/Fisheye/test
```

### Wrong Scene
```
⚠️  Scene 'S99' not in parent directory scenes: S01, S02
Use anyway? (y/n):
```

### Wrong Type
```
⚠️  Type code 'T' doesn't match expected 'F'
Use anyway? (y/n):
```

### Invalid Format
```
⚠️  Invalid pattern. Expected: SXX__F__
Use anyway? (y/n):
```

## Code Organization

The feature is cleanly separated in the code:

```python
# ========================================================================
# HDR SUBDIRECTORY VALIDATION FEATURE
# ========================================================================

def check_hdr_subdirectories(...)
def _validate_hdr_subdir_name(...)
def fix_hdr_subdirectory(...)
def _get_custom_hdr_prefix(...)
```

This separation makes it:
- Easy to maintain independently
- Clear and readable
- Simple to extend

## Benefits

1. **Consistency**: Ensures all HDR data follows same naming convention
2. **Traceability**: Scene code in filename makes it easy to match with shoot day
3. **Organization**: Type codes (F/T/U) clearly identify capture method
4. **Flexibility**: Custom prefix option handles edge cases
5. **Safety**: Multiple validation checks prevent mistakes
