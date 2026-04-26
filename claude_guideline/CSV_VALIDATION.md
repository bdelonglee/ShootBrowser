# CSV Code Validation Feature

## Overview

The sanity check script now validates directory codes and scene-code combinations against the `Editorial_VFX_Code_List.csv` file.

## CSV File Format

The script expects a CSV file at the root level: `Editorial_VFX_Code_List.csv`

**Required columns**:
- `Scene`: Scene number (not padded, e.g., "1", "15", "100", "065A")
- `Sequence Code`: 4-letter code(s), can be multiple separated by `/`

**Example CSV structure**:
```csv
,Scene,Sequence Code,Sequence LongName,...
,1,OPEN,Opening,...
,19,PORT,Heliport,...
,20,MONT,Montparnasse,...
,37,RIDE,Ride,...
,38,DAME,Notre Dame,...
```

## Important: Multi-Code Handling

**Codes are separated by underscore (`_`) in directory names:**
- `__PONT__` = single code: PONT
- `__PONT_PISC__` = two codes: PONT and PISC
- `__PONT_PISC_PLAN__` = three codes: PONT, PISC, and PLAN

The script automatically splits codes by `_` and validates each individually.

## Validation Checks

The script performs two separate checks:

### 1. Code Existence Check

**What it checks**: Are all codes used in day directories present in the CSV?

**Example issue**:
```
📋 Checking: J01__S19__FAKE__Test_Directory
  ⚠️  Code 'FAKE' not found in Editorial_VFX_Code_List.csv
```

This means the code `FAKE` is used in a directory but doesn't exist in the CSV file.

### 2. Scene-Code Combination Check

**What it checks**: Is the combination of scene(s) and code(s) valid according to the CSV?

**Example issue**:
```
📋 Checking: PJ03__S37_S38__POUR__Notre_Dame
  ⚠️  Scene S37 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S37: RIDE
      Directory codes: POUR
  ⚠️  Scene S38 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S38: DAME
      Directory codes: POUR
```

**Multi-code example**:
```
📋 Checking: PJ04__S01_S02__CAST_RITZ__Regina_Exterieur
  ⚠️  Scene S01 / Codes [CAST / RITZ] - none match expected codes in CSV
      Expected codes for scene S01: OPEN
      Directory codes: CAST, RITZ
```

This means:
- The directory uses code `POUR` for scenes S37 and S38
- But according to the CSV:
  - Scene 37 should use code `RIDE`
  - Scene 38 should use code `DAME`

## Usage

### Enable CSV Validation (Default)

```bash
# CSV validation is enabled by default
python3 sanity_check.py

# Output:
# 📊 Loading Editorial VFX Code List...
#    ✅ Loaded 42 codes for 92 scenes
```

### Disable CSV Validation

```bash
# Skip CSV checks if needed
python3 sanity_check.py --no-csv

# CSV loading step is skipped
```

### Example Output

```
======================================================================
🎬 VFX SHOOT DATA SANITY CHECK
======================================================================

📁 Parsing template: /Volumes/MACGUFF001/POSEIDON/DATA_rename/J00_TEMPLATE
   Found 21 template directories

📊 Loading Editorial VFX Code List...
   ✅ Loaded 42 codes for 92 scenes

📂 Scanning day directories...
   Found 19 day directories


📋 Checking: PJ03__S37_S38__POUR__Notre_Dame
  ❌ Empty directory without __ prefix: 20_HDR
  ⚠️  Scene S37 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S37: RIDE
      Directory codes: POUR
  ⚠️  Scene S38 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S38: DAME
      Directory codes: POUR

📋 Checking: PJ03__S37_S38__RIDE_DAME__Remontee_Lilith
  ✅ All checks passed

...

======================================================================
📊 SUMMARY
======================================================================
Total directories checked: 19
Errors: 4
Warnings: 3

🔴 ERRORS FOUND:
❌ Invalid directory naming: J08__S08__PLAN

🟡 WARNINGS:

📋 DIRECTORIES WITH CSV INCONSISTENCIES:
   - PJ03__S37_S38__POUR__Notre_Dame
   - PJ04__S01_S02__CAST_RITZ__Regina_Exterieur
======================================================================
```

The summary now includes a dedicated **"DIRECTORIES WITH CSV INCONSISTENCIES"** section that lists all directories with scene-code validation warnings.

## Interpretation

### ✅ All checks passed
- Directory structure is correct
- Prefix rules followed
- Codes exist in CSV
- Scene-code combinations are valid

### ⚠️ CSV Warnings
- These are **warnings**, not errors
- The directory might be valid but doesn't match the editorial list
- All directories with CSV warnings are listed in the summary under **"DIRECTORIES WITH CSV INCONSISTENCIES"**
- Common reasons:
  - Directory created before CSV was updated
  - Multiple codes combined (e.g., `RIDE_DAME` for scenes that span both)
  - Editorial changes not yet reflected in directory names

### ❌ Errors
- Structural issues (prefix consistency, naming patterns)
- These should be fixed

## Special Cases

### Multi-Code Directories

When a directory combines multiple codes (e.g., `__RIDE_DAME__`):
- The underscore `_` separates individual codes: RIDE and DAME
- The script checks each code separately
- Valid if **any** code matches the scene's expected codes

**Example**:
```
Directory: PJ03__S37_S38__RIDE_DAME__Remontee_Lilith

Validation:
- Directory codes: RIDE, DAME
- Scene S37 expects: RIDE
  → RIDE matches ✅
- Scene S38 expects: DAME
  → DAME matches ✅
- Result: Valid combination
```

**Another example with 3 codes**:
```
Directory: J05__S08__PONT_PISC_PLAN__Multiple_Locations

Validation:
- Directory codes: PONT, PISC, PLAN (all validated individually)
- Scene S08 expects: PLAN
  → PLAN matches ✅
- Result: Valid (at least one code matches)
```

### Multi-Scene Directories

When a directory spans multiple scenes:
- Each scene is validated independently
- At least one directory code must match each scene's expected codes

**Example with mismatch**:
```
Directory: PJ03__S37_S38__POUR__Notre_Dame

Validation:
- Directory codes: POUR
- Scene S37 expects: RIDE
  → POUR doesn't match ❌
- Scene S38 expects: DAME
  → POUR doesn't match ❌
- Result: Warnings for both scenes

Error shown:
  ⚠️  Scene S37 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S37: RIDE
      Directory codes: POUR
  ⚠️  Scene S38 / Codes [POUR] - none match expected codes in CSV
      Expected codes for scene S38: DAME
      Directory codes: POUR
```

### Special Scene Numbers

The CSV can contain:
- Numeric scenes: `1`, `19`, `100`
- Lettered variations: `065A`, `085B`
- The script strips letters for matching: `065A` → `65`

## CSV File Location

The script looks for: `<data_path>/Editorial_VFX_Code_List.csv`

**Default path**: `/Volumes/MACGUFF001/POSEIDON/DATA_rename/Editorial_VFX_Code_List.csv`

**If CSV is missing**:
```
📊 Loading Editorial VFX Code List...
   ⚠️  CSV file not found or could not be loaded
   Skipping CSV validation
```

The script continues without CSV validation - no errors.

## Code Organization

The CSV validation feature is cleanly separated in the code:

```python
# ========================================================================
# CSV CODE VALIDATION FEATURE
# ========================================================================

def load_csv_code_list(self) -> bool:
    """Load and parse the Editorial_VFX_Code_List.csv file"""
    # ...

def validate_codes_against_csv(self, dir_info: DirectoryInfo) -> List[str]:
    """Validate directory codes and scenes against CSV data"""
    # ...
```

This separation makes it easy to:
- Enable/disable the feature
- Maintain independently
- Extend with additional checks

## Workflow Integration

### Recommended Workflow

1. **Run sanity check** to see all issues
   ```bash
   python3 sanity_check.py
   ```

2. **Fix structural issues first** (prefix, naming)
   ```bash
   python3 sanity_check.py --fix
   ```

3. **Review CSV warnings**
   - Check if directory naming needs updating
   - Or update CSV if editorial changed

4. **Skip CSV temporarily** if needed during active production
   ```bash
   python3 sanity_check.py --no-csv --fix
   ```

## Benefits

1. **Early Detection**: Catch naming mismatches before they become problems
2. **Editorial Alignment**: Ensure directories match the editorial plan
3. **Documentation**: CSV serves as source of truth for scene-code mapping
4. **Flexible**: Can be disabled when not needed
