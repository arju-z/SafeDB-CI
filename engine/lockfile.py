"""
engine/lockfile.py — Migration Tamper Detection

PURPOSE:
After a successful validation run, SafeDB-CI records the SHA-256 hash of
every migration file in a JSON lockfile (.safedb-lock). On subsequent runs,
any change to a previously-locked file is detected and treated as a hard error.

WHY THIS MATTERS:
The most common cause of schema drift incidents after "missing migration" is
"someone edited a committed migration instead of writing a new one." This
module catches that at Phase 1b — before any DB connection is opened.

DESIGN CONSTRAINTS:
- No external dependencies. Uses only `hashlib`, `json`, `pathlib`.
- Read-only during validation. Written only on success.
- New migration files (not yet in the lockfile) are not an error — they
  will be hashed and added to the lockfile on the next successful run.
- The lockfile should be committed to version control. It is the ground truth.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine.models import Migration


# ── Constants ──────────────────────────────────────────────────────────────────

# Default lockfile name. Can be overridden via --lockfile-path.
DEFAULT_LOCKFILE_NAME = ".safedb-lock"

# Algorithm used for hashing. SHA-256 is collision-resistant and universally
# available in Python's hashlib without extra dependencies.
HASH_ALGORITHM = "sha256"


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class TamperViolation:
    """
    Represents a detected tamper event — a migration file whose content has
    changed since it was last validated.

    Attributes:
        filename:      The migration file that was tampered.
        expected_hash: The SHA-256 hash recorded in the lockfile.
        actual_hash:   The SHA-256 hash computed from the current file content.
    """
    filename: str
    expected_hash: str
    actual_hash: str


# ── Hashing ────────────────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str:
    """
    Compute the SHA-256 hash of a file's contents.

    WHY READ IN CHUNKS: Migration files are small (usually < 10KB), but we
    read in chunks defensively to be safe against very large files without
    loading the entire content into memory at once.

    Returns a hex digest string prefixed with the algorithm name, e.g.:
        "sha256:a3b4c5d6..."
    """
    hasher = hashlib.new(HASH_ALGORITHM)
    with open(path, "rb") as f:
        # 64KB chunks — appropriate for file sizes we expect.
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return f"{HASH_ALGORITHM}:{hasher.hexdigest()}"


# ── Lockfile I/O ───────────────────────────────────────────────────────────────

def load_lockfile(lockfile_path: Path) -> Optional[dict]:
    """
    Load and parse the lockfile from disk.

    Returns None if the lockfile does not exist yet (first run).
    Raises ValueError if the file exists but is not valid JSON.

    WHY NOT RAISE ON MISSING: A missing lockfile is not an error — it simply
    means this is the first successful run and no history exists yet.
    """
    if not lockfile_path.exists():
        return None

    try:
        with open(lockfile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # A corrupt lockfile is a hard error. Do not silently ignore it —
        # that would allow a tampered lockfile to bypass tamper detection.
        raise ValueError(
            f"Lockfile at '{lockfile_path}' is corrupt or not valid JSON: {e}"
        )

    return data


def write_lockfile(migrations: list[Migration], lockfile_path: Path) -> None:
    """
    Write a new lockfile recording the current hashes of all migration files.

    Called ONLY after all 6 phases complete successfully. Writing on failure
    would record a broken state as the new baseline.

    WHY INCLUDE TIMESTAMP: For audit and debugging purposes only. The timestamp
    is not used in tamper checking — only the hashes matter.
    """
    entries: dict[str, str] = {}
    for migration in migrations:
        entries[migration.filename] = _hash_file(migration.path)

    lockfile_data = {
        "safedb_version": "2.0.0",
        "last_validated": datetime.now(timezone.utc).isoformat(),
        "migrations": entries,
    }

    with open(lockfile_path, "w", encoding="utf-8") as f:
        json.dump(lockfile_data, f, indent=2)
        f.write("\n")  # POSIX trailing newline — avoids "no newline at EOF" diffs.

    print(f"Lockfile updated: {lockfile_path} ({len(entries)} migration(s) recorded)")


# ── Tamper check ───────────────────────────────────────────────────────────────

def check_tamper(
    migrations: list[Migration],
    lockfile_data: dict,
) -> list[TamperViolation]:
    """
    Compare the current migration file hashes against the lockfile.

    Logic:
    - If a file is in the lockfile and its hash matches: ✅ clean
    - If a file is in the lockfile and its hash changed:  ❌ TAMPER DETECTED
    - If a file is NOT in the lockfile (new migration):   ✅ clean (will be added on next success)
    - Lockfile entries for files that no longer exist:    ✅ ignored here
      (ordering check in Phase 1 will have already caught missing files)

    WHY RETURN A LIST (not raise immediately): We want to report ALL tampered
    files at once, not halt on the first one. Force the developer to fix
    everything in a single pass.
    """
    locked_hashes: dict[str, str] = lockfile_data.get("migrations", {})
    violations: list[TamperViolation] = []

    for migration in migrations:
        if migration.filename not in locked_hashes:
            # New migration — not previously validated. Not an error.
            continue

        expected_hash = locked_hashes[migration.filename]
        actual_hash = _hash_file(migration.path)

        if actual_hash != expected_hash:
            violations.append(TamperViolation(
                filename=migration.filename,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
            ))

    return violations
