"""
Safety check — scans Python files for dangerous DB patterns.
Run standalone: python safety_check.py
Also called from main.py on startup.
"""
import glob
import os
import sys

# Patterns that could wipe data if misused
DANGEROUS_PATTERNS = [
    ("drop_all", "Could drop all database tables"),
    ("DROP TABLE", "Raw SQL table drop"),
    ("TRUNCATE", "Raw SQL truncate"),
    (".delete()\n", "Bulk delete without WHERE clause — use .filter().delete()"),
]

# Files that are allowed to contain these patterns
ALLOWED_FILES = {
    "safety_check.py",  # This file
    "seed.py",          # Seed script (reviewed, has safety guards)
    "setup_db.py",      # Setup script (reviewed)
}


def check_safety(base_dir=None):
    """Scan all .py files for dangerous patterns. Returns list of violations."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    violations = []
    for filepath in glob.glob(os.path.join(base_dir, "**/*.py"), recursive=True):
        filename = os.path.basename(filepath)
        if filename in ALLOWED_FILES:
            continue

        try:
            with open(filepath) as f:
                content = f.read()
        except Exception:
            continue

        for pattern, reason in DANGEROUS_PATTERNS:
            # Check each line — skip comments
            for line_num, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if pattern in line:
                    rel_path = os.path.relpath(filepath, base_dir)
                    violations.append({
                        "file": rel_path,
                        "line": line_num,
                        "pattern": pattern,
                        "reason": reason,
                    })
                    break  # One violation per pattern per file is enough

    return violations


def run_check():
    """Run check and print results."""
    violations = check_safety()
    if violations:
        print(f"[SAFETY WARNING] {len(violations)} dangerous pattern(s) found:")
        for v in violations:
            print(f"  {v['file']}: '{v['pattern']}' — {v['reason']}")
    else:
        print("[SAFETY] All clear — no dangerous patterns found outside allowed files.")
    return violations


if __name__ == "__main__":
    violations = run_check()
    sys.exit(1 if violations else 0)
