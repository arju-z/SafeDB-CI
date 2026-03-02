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


def _normalize_sql(sql: str) -> str:
    """
    Normalizes raw SQL text before scanning.

    WHY NORMALIZE:
    - Strip out single-line comments (-- ...) to avoid false positives from
      commented-out SQL, like our own inline documentation.
    - Strip block comments (/* ... */) for the same reason.
    - Collapse duplicate whitespace to make regex matching more predictable.
    - We do NOT lowercase here because some rules need to preserve line structure
      for MULTILINE anchors on real content.

    WHY NOT REMOVE ALL COMMENTS:
    We only remove -- and /* */ style comments. String literals that happen to
    contain comment-like characters inside actual SQL VALUES are rare in migrations
    and acceptable as a known edge case.
    """
    # Remove single-line comments (-- to end-of-line)
    sql = re.sub(r"--[^\n]*", "", sql)

    # Remove block comments (/* ... */)
    # re.DOTALL ensures '.' also matches newlines inside block comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

    # Normalize repeated whitespace (tabs, newlines, extra spaces) into single spaces
    # This prevents patterns like "DROP\nTABLE" from slipping through
    sql = re.sub(r"\s+", " ", sql)

    return sql.strip()


def analyze_migration(filename: str, sql: str) -> List[SafetyViolation]:
    """
    Scans a single migration's SQL text for destructive patterns.

    Returns a list of SafetyViolation objects. An empty list means clean.

    WHY A LIST (not a single raise): A single migration may have multiple violations.
    We want to report ALL of them at once so the developer can fix everything in one
    pass, rather than discovering them one-by-one as the scanner halts.

    Args:
        filename: The migration filename (for error reporting only, not I/O).
        sql:      The raw SQL file text to analyze.
    """
    violations: List[SafetyViolation] = []

    # Normalize first to avoid comment-based bypasses and whitespace tricks
    normalized = _normalize_sql(sql)

    for rule_name, pattern, severity in _RULES:
        matches = pattern.finditer(normalized)

        for match in matches:
            # Extract a short window around the match for readable context
            # We pull 60 characters on either side of the matched position
            # WHY: Showing the full normalized SQL per match would be extremely verbose
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
