# Safety Features Documentation

## Overview

The sanity check script has been enhanced with comprehensive safety features to ensure robust and safe operation when fixing directory prefix issues.

## Safety Features

### 1. **Path Validation**

#### Data Path Validation
- Validates data path exists before starting
- Ensures data path is actually a directory
- Resolves to absolute path to avoid ambiguity
- **Error if path doesn't exist or isn't a directory**

```python
if not self.data_path.exists():
    raise ValueError(f"Data path does not exist: {self.data_path}")
```

#### Runtime Path Checks
- Validates paths still exist before renaming (guards against concurrent modifications)
- Ensures target is a directory, not a file
- Checks parent directory still exists
- **Skips rename if path became invalid**

### 2. **Permission Checks**

#### Write Permission Validation
- In `--fix` mode, checks write permissions on data directory before starting
- Fails fast if no write access
- Prevents wasting time scanning if fixes can't be applied

```bash
python3 sanity_check.py --fix
# ❌ Error: No write permission for /path
# Cannot use --fix mode without write access
```

#### Per-Operation Permission Handling
- Catches `PermissionError` during each rename
- Continues with other fixes if one fails
- Clear error message: "Permission denied"

### 3. **Conflict Detection**

#### Pre-Flight Validation
Before asking user to fix, validates all planned renames:

1. **Duplicate Target Detection**
   - Checks if multiple renames would create the same target name
   - Example: Both `20_HDR` and `20_hdr` renaming to `__20_HDR` on case-insensitive filesystem

2. **Existing Target Detection**
   - Checks if target name already exists in filesystem
   - Prevents accidental overwrites

3. **Automatic Abort**
   - If conflicts detected, shows errors and refuses to proceed
   - User never asked to fix if validation fails

```
Found 4 fixable prefix issue(s) in Day_X
⚠️  Cannot fix automatically due to conflicts:
    - 20_HDR/Theta: target __Theta already exists
⏭️  Skipped fixes
```

### 4. **Symlink Protection**

- Detects and skips symbolic links
- Prevents following symlinks outside expected directory tree
- **Won't rename symlinks** - shows warning and skips

```
⚠️  Skipping symlink: path/to/symlink
```

### 5. **Path Traversal Protection**

- Security check: ensures all paths are within expected day directory
- Uses `relative_to()` to validate path hierarchy
- Prevents malicious or corrupted data from causing renames outside scope

```python
try:
    old_path.relative_to(issue.parent_day_path)
except ValueError:
    # Path is outside expected directory - ABORT
```

### 6. **Atomic Operations**

- Uses `Path.rename()` which is atomic on most filesystems
- Either rename succeeds completely or fails completely
- No partial rename states

### 7. **Correct Ordering**

#### Depth-First Processing
- Sorts fixes by path depth (deepest first)
- **Children renamed before parents**
- Prevents invalid path errors when parent moves

Example:
```
✅ Correct order:
   1. __20_HDR/Fisheye → __20_HDR/__Fisheye (child first)
   2. __20_HDR → 20_HDR (parent last)

❌ Wrong order would cause:
   1. __20_HDR → 20_HDR (parent first)
   2. __20_HDR/Fisheye → FAILS (path no longer exists!)
```

### 8. **Hidden Directory Filtering**

- Automatically skips hidden directories (starting with `.`)
- Prevents scanning/modifying system directories like `.git`, `.DS_Store`
- Modified `os.walk()` to filter hidden dirs:

```python
dirs[:] = [d for d in dirs if not d.startswith('.')]
```

### 9. **Input Validation**

#### User Input Handling
- Validates user responses (y/yes/n/no)
- Handles keyboard interrupts (`Ctrl+C`) gracefully
- Handles EOF errors (piped input)

#### Name Validation
- Ensures new names are not empty
- Prevents creating hidden directories (names starting with `.`)
- Validates prefix removal (checks `__` actually exists before removing)

### 10. **Error Handling Hierarchy**

```python
try:
    # Perform rename
except PermissionError:
    # Specific handler for permission issues
except OSError as e:
    # Handler for filesystem errors
except Exception as e:
    # Catch-all for unexpected errors
```

Each error type gets appropriate error message and handling.

### 11. **Graceful Interruption**

#### Keyboard Interrupt (Ctrl+C)
- Catches `KeyboardInterrupt` at multiple levels
- Shows clear message about partial completion
- Suggests re-running to check status
- Uses proper exit code (130 for SIGINT)

```
⚠️  Fix process interrupted by user
Some directories may have been renamed. Run again to check status.
```

### 12. **Read-Only by Default**

- Default mode is **read-only** - never modifies anything
- Requires explicit `--fix` flag to enable modifications
- Safe to run repeatedly without side effects

```bash
# Safe - only reports issues
python3 sanity_check.py

# Requires explicit flag to modify
python3 sanity_check.py --fix
```

### 13. **Per-Day Confirmation**

- Asks user approval **for each day directory**
- User can selectively fix some days and skip others
- Shows count of issues before asking
- Can abort at any time

### 14. **Detailed Feedback**

- Shows exactly what will be renamed before doing it
- Reports success/failure for each operation
- Counts and displays: `Fixed X/Y issue(s)`
- Clear distinction between warnings (⚠️), errors (❌), and success (✅)

### 15. **Idempotent Operation**

- Running the script multiple times is safe
- Already-fixed directories show "✅ All checks passed"
- Can re-run after partial fixes to continue where left off

## What's NOT Protected Against

While the script is robust, there are some limitations:

1. **Concurrent Access**
   - No file locking - don't run multiple instances simultaneously
   - Don't modify directories while script is running

2. **Disk Space**
   - Doesn't check available disk space
   - Rename operations should be instantaneous on same filesystem

3. **Filesystem Errors**
   - Can't protect against disk failures, corruption, etc.
   - These will cause appropriate error messages

4. **Network Filesystems**
   - NFS/SMB mounted drives may have different atomicity guarantees
   - Rename operations might not be atomic

## Best Practices

1. **Backup First** (for important data)
   ```bash
   # Optional but recommended
   rsync -av /Volumes/MACGUFF001/POSEIDON/DATA_rename/ /path/to/backup/
   ```

2. **Test Mode First**
   ```bash
   # See what needs fixing (read-only)
   python3 sanity_check.py
   ```

3. **Review Before Fixing**
   - Read the issues reported
   - Understand what will be renamed
   - Then run with `--fix`

4. **Fix Incrementally**
   - Can say 'n' to skip days you want to review manually
   - Fix a few days, verify, then continue

5. **Verify After Fixing**
   ```bash
   # After running --fix, verify all issues resolved
   python3 sanity_check.py
   ```

6. **Single User**
   - Only one person should run the script at a time
   - Coordinate with team if working on shared storage

## Error Recovery

If something goes wrong mid-fix:

1. **Check Current State**
   ```bash
   python3 sanity_check.py
   ```

2. **Review What Was Fixed**
   - Script shows exactly what it renamed
   - Some dirs may have new names

3. **Continue Fixing**
   ```bash
   python3 sanity_check.py --fix
   ```
   - Script will detect remaining issues
   - Can continue from where it stopped

4. **Manual Rollback** (if needed)
   - Rename operations are simple `mv` operations
   - Can manually reverse: `mv __Theta Theta`

## Testing Performed

The script has been tested with:
- ✅ Empty directories without `__` prefix
- ✅ Non-empty directories with `__` prefix
- ✅ Nested directory hierarchies (children + parents)
- ✅ Paths with special characters
- ✅ Permission errors
- ✅ Concurrent rename conflicts
- ✅ Keyboard interrupts
- ✅ Invalid paths
- ✅ Symlinks
- ✅ Hidden directories

## Security Considerations

1. **No Remote Code Execution**: Script only renames directories, doesn't execute files
2. **Path Traversal Protection**: Can't rename outside day directories
3. **No Data Loss**: Only renames directories, doesn't delete anything
4. **Input Validation**: User input is validated and sanitized
5. **Least Privilege**: Only requires write access to directories being fixed

## Exit Codes

- `0`: Success (all checks passed)
- `1`: Errors found or operation failed
- `130`: User interrupted with Ctrl+C

## Conclusion

The script is designed to be **safe by default** with multiple layers of protection. The `--fix` mode has extensive validation and user confirmation to prevent accidents while remaining convenient for legitimate use.
