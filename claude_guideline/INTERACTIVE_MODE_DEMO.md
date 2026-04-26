# Interactive Fix Mode Demo

## How to Use

The sanity check script now supports an interactive fix mode that will ask you to approve fixes for each day directory that has prefix inconsistencies.

## Running Interactive Mode

```bash
# Run with --fix flag to enable interactive mode
python3 sanity_check.py --fix

# Or specify a custom path
python3 sanity_check.py /path/to/DATA_rename --fix
```

## What Happens

When running in interactive mode:

1. The script scans all day directories as usual
2. For each day that has prefix issues, it will:
   - Display all the issues found
   - Ask: "Do you want to fix them? (y/n):"
   - Wait for your response

3. If you answer **'y' or 'yes'**:
   - The script will automatically rename directories to fix the issues
   - Empty directories will get `__` prefix added
   - Non-empty directories will have `__` prefix removed
   - Shows what was renamed

4. If you answer **'n' or 'no'**:
   - Skips fixes for that day
   - Continues to the next day

## Example Session

```
======================================================================
🎬 VFX SHOOT DATA SANITY CHECK
(Interactive Fix Mode)
======================================================================

📁 Parsing template: /Volumes/MACGUFF001/POSEIDON/DATA_rename/J00_TEMPLATE
   Found 21 template directories

📂 Scanning day directories...
   Found 19 day directories


📋 Checking: J01__S19__PORT__Montparnasse_Exterieur
  ❌ Empty directory without __ prefix: 20_HDR/Theta
  ❌ Empty directory without __ prefix: 20_HDR/Theta_Underwater

  Found 2 fixable prefix issue(s) in J01__S19__PORT__Montparnasse_Exterieur
  Do you want to fix them? (y/n): y
      ✅ Renamed: Theta → __Theta
      ✅ Renamed: Theta_Underwater → __Theta_Underwater

  ✅ Fixed 2/2 issue(s)


📋 Checking: J01__S20__MONT__Montparnasse_Interieur
  ❌ Empty directory without __ prefix: 70_Temoin_Videos
  ⚠️  Non-empty directory with __ prefix: __20_HDR
  ❌ Empty directory without __ prefix: __20_HDR/Fisheye
  ❌ Empty directory without __ prefix: __20_HDR/Theta
  ❌ Empty directory without __ prefix: __20_HDR/Theta_Underwater

  Found 5 fixable prefix issue(s) in J01__S20__MONT__Montparnasse_Interieur
  Do you want to fix them? (y/n): n
  ⏭️  Skipped fixes


📋 Checking: PJ03__S80__EIFF__Tour_Eiffel_Cachette
  ✅ All checks passed
```

## What Gets Fixed

### Missing `__` Prefix
Empty directories will be renamed to add the `__` prefix:
- `20_HDR` → `__20_HDR` (if empty)
- `Theta` → `__Theta` (if empty)
- `60_Temoin_Photos` → `__60_Temoin_Photos` (if empty)

### Extra `__` Prefix
Non-empty directories will be renamed to remove the `__` prefix:
- `__20_HDR` → `20_HDR` (if contains files)
- `__70_Temoin_Videos` → `70_Temoin_Videos` (if contains files)

## Safety Features

- **Prompts for each day**: You approve fixes day by day
- **Shows what will be renamed**: Clear before/after names
- **Checks for conflicts**: Won't rename if target name already exists
- **Error handling**: If a rename fails, it continues with other fixes
- **Count summary**: Shows how many fixes succeeded

## Tips

1. **Review before fixing**: Run without `--fix` first to see all issues
2. **Fix one day at a time**: You can say 'n' to skip days you want to review manually
3. **Backup first**: Consider backing up your data before running fixes
4. **Re-run after fixing**: Run the script again to verify all issues are resolved

## Non-Interactive Mode (Default)

Without the `--fix` flag, the script runs in read-only mode:
```bash
python3 sanity_check.py
```

This is safe to run anytime - it only reports issues, never modifies anything.
