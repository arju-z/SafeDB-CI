"""
engine/safety.py

WHY THIS MODULE EXISTS:
The CI validation database is always empty. A migration containing `DROP TABLE users`
will execute and succeed against an empty database, but will destroy gigabytes of
real production data when deployed.

We must detect *intent* — not just outcome. The CI database cannot simulate data loss.
A regex-based pattern scanner can. This module is a guardrail, not a full SQL parser.

WHY NOT A FULL SQL PARSER:
- SQL dialects (PostgreSQL, MySQL, SQLite) differ significantly.
- Full parsers (like sqlparse or antlr) add heavy dependencies, are hard to pin,
  and introduce their own set of failure modes.
- We are not validating SQL syntax here; psycopg/mysql.connector already does that.
- We are detecting *intent patterns*. Regex is deterministic, auditable, and fast.

KNOWN LIMITATIONS (SEE BOTTOM OF FILE):
- Regex can have false positives.
- Regex cannot fully understand SQL semantics or nested expressions.
- This is a guardrail. Treat it as a first line of defense, not a guarantee.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List

from engine.errors import MigrationError


class Severity(str, Enum):
    """
    Severity levels for detected safety issues.

    HIGH = blocks the entire migration run. Fail immediately.
    MEDIUM = warns but allows execution to proceed by default.

    WHY TWO LEVELS: Not all dangerous SQL is equally dangerous in all contexts.
    An ALTER COLUMN TYPE on a low-traffic auxiliary table warrants a warning.
    A DROP TABLE on a financial ledger warrants an immediate CI block.
    """
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


@dataclass
class SafetyViolation:
    """
    Represents a single detected dangerous pattern.

    WHY A DATACLASS: We want a structured, inspectable object — not a raw string.
    This allows the CLI to iterate violations and format them clearly for
    both human developers and potential future structured log output.
    """
    filename: str       # The migration file where the pattern was detected
    rule: str           # Human-readable name of the rule that triggered
    severity: Severity  # HIGH or MEDIUM
    pattern: str        # The specific pattern that was detected in the SQL
    line: str           # The raw source line that matched, for context


class SafetyError(MigrationError):
    """
    Raised when a HIGH severity violation is detected.

    WHY INHERIT FROM MigrationError: The CLI already has a clean catch block for
    MigrationError that maps it to exit code 1 without printing a stack trace.
    By inheriting from it, we get CI-safe error propagation for free without
    touching the executor or adapter layers.
    """
    pass


# ---------------------------------------------------------------------------
# RULE DEFINITIONS
# ---------------------------------------------------------------------------
# Each rule is a tuple of:
#   (rule_name, compiled_regex, severity)
#
# WHY PRE-COMPILE: re.compile() builds the state machine once at import time.
# This avoids recompiling the same patterns for every migration file processed.
#
# WHY re.IGNORECASE: SQL keywords are case-insensitive. A developer may write
# "drop table", "DROP TABLE", or "Drop Table". We must catch all of these.
#
# WHY re.MULTILINE: Migration files can be multi-line. We want `^` to anchor
# to the start of each logical line, not just the start of the entire file.
# ---------------------------------------------------------------------------

_RULES: List[tuple] = [
    (
        "DROP TABLE",
        re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
        Severity.HIGH,
    ),
    (
        "DROP COLUMN",
        re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
        Severity.HIGH,
    ),
    (
        "TRUNCATE",
        # TRUNCATE can appear as 'TRUNCATE TABLE' or just 'TRUNCATE tablename'
        re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
        Severity.HIGH,
    ),
    (
        "ALTER TABLE ... DROP",
        # Catches ALTER TABLE foo DROP (without requiring the word COLUMN next)
        # This handles some dialect-specific variants like MySQL's shorthand
        re.compile(r"\bALTER\s+TABLE\s+\S+\s+DROP\b", re.IGNORECASE),
        Severity.HIGH,
    ),
    (
        "CASCADE",
        # CASCADE modifies the blast radius of DROP/DELETE.
        # WHY MEDIUM (not HIGH): `ON DELETE CASCADE` on a FK definition is conditional —
        # it only fires when a parent row is explicitly deleted. This is frequently
        # intentional (e.g. deleting a user should delete their sessions).
        # It is different from DROP TABLE or TRUNCATE which unconditionally destroy ALL data.
        # We warn so the reviewer confirms the blast radius is intended.
        re.compile(r"\bCASCADE\b", re.IGNORECASE),
        Severity.MEDIUM,
    ),
    (
        "DELETE without WHERE",
        # A DELETE without a WHERE clause is an unconditional table wipe.
        # WHY NEGATIVE LOOKAHEAD is NOT used: Regex cannot reliably detect the
        # absence of a WHERE clause that might appear on a later line.
        # We detect "DELETE FROM <something>" and assume it's unconditional.
        # This is a known false-positive source — a deliberate trade-off.
        # A full-table delete is almost never correct in a migration file.
        re.compile(r"\bDELETE\s+FROM\s+\S+\s*$", re.IGNORECASE | re.MULTILINE),
        Severity.HIGH,
    ),
    (
        "ALTER COLUMN TYPE",
        # Type changes can silently truncate data or raise implicit cast errors
        # in production when actual rows exist.
        # Detected at MEDIUM because it may be intentional.
        re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b", re.IGNORECASE),
        Severity.MEDIUM,
    ),
    (
        "ALTER COLUMN SET NOT NULL",
        # Adding NOT NULL to a column that has any NULL values will fail in prod
        # even though it passed fine against the empty CI DB.
        re.compile(r"\bSET\s+NOT\s+NULL\b", re.IGNORECASE),
        Severity.MEDIUM,
    ),
]


"""
SAFETY OVERRIDE ANNOTATION — safedb:allow
==========================================
A destructive statement can be explicitly approved by a reviewer using the
`-- safedb:allow` annotation. This must appear either:

  - INLINE on the same line as the dangerous statement:
      DROP TABLE legacy_import_cache; -- safedb:allow

  - OR on the IMMEDIATELY PRECEDING LINE:
      -- safedb:allow
      DROP TABLE legacy_import_cache;

The annotation causes the line (and any immediately preceded line match) to
be stripped from safety scanning. A log message is emitted so the bypass is
permanently visible in CI output — it cannot be silent.

WHY NOT A GLOBAL FILE OVERRIDE:
A file-level `-- safedb:allow-file` would let a single annotation skip all
scanning in a file, making it easy to accidentally suppress unintended patterns.
Line-level annotations are deliberately narrow: each risky statement must be
individually and explicitly reviewed.
"""

# The marker string (lowercase for case-insensitive matching)
_ALLOW_MARKER = "safedb:allow"


def _is_allowed(line: str) -> bool:
    """Return True if the line carries a safedb:allow annotation."""
    return _ALLOW_MARKER in line.lower()


def _normalize_sql(sql: str) -> str:
    """
    Normalizes raw SQL text before scanning.

    This version ONLY strips block comments (/* ... */) and normalizes whitespace.
    Single-line (-- ...) comments are NOT stripped here because the allow-marker
    check must happen before normalization. Individual -- lines irrelevant to
    safety scanning are excluded by analyze_migration's line filter before this
    function is called.
    """
    # Remove block comments (/* ... */)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    # Normalize repeated whitespace into single spaces.
    # This prevents patterns like "DROP\nTABLE" from escaping detection.
    sql = re.sub(r"\s+", " ", sql)

    return sql.strip()


def analyze_migration(filename: str, sql: str) -> List[SafetyViolation]:
    """
    Scans a single migration's SQL text for destructive patterns.

    Returns a list of SafetyViolation objects. An empty list means clean.

    ALLOW ANNOTATION LOGIC:
    Before normalization, we scan the raw SQL line-by-line.
    Any line tagged with `-- safedb:allow` (inline or as the PRECEDING line)
    is removed from the text that goes to the regex scanner.
    A printed log message ensures the bypass is always auditable in CI.

    WHY LINE-BY-LINE (not whole-file regex):
    A whole-file approach lets one annotation silence a whole block.
    Per-line resolution means each dangerous statement needs its own explicit
    acknowledgement — intentional friction that encourages careful review.

    Args:
        filename: The migration filename (for error reporting only, not I/O).
        sql:      The raw SQL file text to analyze.
    """
    violations: List[SafetyViolation] = []
    allowed_lines: List[int] = []  # 0-indexed line numbers exempt from scanning

    raw_lines = sql.splitlines()

    # --- Pass 1: Identify lines to exclude -----------------------------------
    #
    # We build a set of line indices that carry or are preceded by safedb:allow.
    # These lines will be blanked out before the SQL is re-joined and normalized.
    for i, line in enumerate(raw_lines):
        if _is_allowed(line):
            # The annotation line itself
            allowed_lines.append(i)
            # If this is a pure annotation line (no SQL), the NEXT line is the
            # statement it covers. Check if the next line is not itself annotated.
            stripped = line.strip().lower()
            is_pure_annotation = stripped == "-- safedb:allow" or stripped.startswith("-- safedb:allow")
            if is_pure_annotation and i + 1 < len(raw_lines):
                allowed_lines.append(i + 1)
                print(
                    f"  [SAFETY OVERRIDE] {filename}:{i + 2}: safedb:allow — reviewer override "
                    f"accepted for: {raw_lines[i + 1].strip()!r}"
                )
            else:
                # Inline annotation: the annotation IS on the dangerous line.
                print(
                    f"  [SAFETY OVERRIDE] {filename}:{i + 1}: safedb:allow — reviewer override "
                    f"accepted for: {line.strip()!r}"
                )

    # --- Pass 2: Blank out allowed lines -------------------------------------
    #
    # Replace allowed lines with empty strings so they don't feed the scanner,
    # but preserve the line count so error positions stay correct if we ever
    # add line-number reporting to violations.
    filtered_lines = [
        "" if i in allowed_lines else line
        for i, line in enumerate(raw_lines)
    ]

    # Also strip remaining pure comment lines (no safedb:allow) before
    # passing to the normalizer — avoids false positives from commented SQL.
    filtered_lines = [
        re.sub(r"--[^\n]*", "", line)
        for line in filtered_lines
    ]

    filtered_sql = "\n".join(filtered_lines)

    # --- Pass 3: Normalize and scan ------------------------------------------
    normalized = _normalize_sql(filtered_sql)

    for rule_name, pattern, severity in _RULES:
        matches = pattern.finditer(normalized)

        for match in matches:
            start = max(0, match.start() - 30)
            end = min(len(normalized), match.end() + 30)
            context_snippet = normalized[start:end].strip()

            violations.append(
                SafetyViolation(
                    filename=filename,
                    rule=rule_name,
                    severity=severity,
                    pattern=match.group(0),
                    line=f"...{context_snippet}...",
                )
            )

    return violations


def run_safety_check(migrations) -> None:
    """
    Runs safety analysis across all loaded Migration objects.
    Called by the CLI before passing to the executor.

    WHY PLACED HERE (not in executor): The executor is responsible for database
    execution and should remain pure. Safety analysis is a static code inspection
    concern separated from runtime execution. Layering it in the CLI keeps the
    executor composable in other non-CLI contexts (tests, scripts).

    Behavior:
        - Collects all violations across all migrations.
        - Prints MEDIUM warnings but does not halt.
        - Raises SafetyError immediately if any HIGH severity violation is found.

    Args:
        migrations: An iterable of Migration objects produced by load_migrations().
    """
    high_violations: List[SafetyViolation] = []
    medium_violations: List[SafetyViolation] = []

    for migration in migrations:
        sql_text = migration.path.read_text(encoding="utf-8")
        violations = analyze_migration(migration.filename, sql_text)

        for v in violations:
            if v.severity == Severity.HIGH:
                high_violations.append(v)
            else:
                medium_violations.append(v)

    # Print all MEDIUM warnings first so they're visible before any fatal error
    for v in medium_violations:
        print(f"  [SAFETY WARNING] [{v.severity}] {v.filename} — {v.rule}")
        print(f"    Context: {v.line}")

    # Now raise for any HIGH violations
    # WHY RAISE AFTER COLLECTING ALL: The developer should see every high-severity
    # issue at once rather than fix one and re-run to discover the next.
    if high_violations:
        # Build a single structured error message listing all violations
        report_lines = [
            f"\nSAFETY CHECK FAILED: {len(high_violations)} HIGH severity violation(s) detected.\n"
        ]
        for v in high_violations:
            report_lines.append(f"  [{v.severity}] {v.filename} — Rule: '{v.rule}'")
            report_lines.append(f"    Detected: '{v.pattern}'")
            report_lines.append(f"    Context:  {v.line}")
            report_lines.append("")

        report_lines.append(
            "These migrations have been BLOCKED from execution.\n"
            "Review each file and confirm the operation is intentional.\n"
            "To intentionally bypass this check, remove the destructive statement\n"
            "or document why it is safe in a separate reviewed migration."
        )

        raise SafetyError("\n".join(report_lines))
