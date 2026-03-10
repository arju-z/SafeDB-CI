"""
engine/naming.py — Schema Naming Heuristics (Phase 5b)

PURPOSE:
Analyses the post-migration schema snapshot for structural patterns that
suggest normalization debt, incomplete FK wiring, or data-type correctness risks.

These are ADVISORY checks. They emit MEDIUM severity warnings by default,
and become hard failures when --strict is active.

DESIGN PHILOSOPHY:
- No AST parsing. No data access. Pure analysis of the SchemaSnapshot
  already held in memory after Phase 4 (introspection).
- Heuristics are named patterns, not proofs. False positives are possible.
  Comments in each check function explain the reasoning and limitations.
- New checks can be added by appending to _run_all_heuristics().
- Checks must NOT modify the snapshot. Read-only.

LIMITATIONS:
- Column name heuristics have a false positive rate. A column named `tag_ids`
  might be a legitimate integer PK in a niche schema. We warn; we don't decide.
- We cannot detect semantic data-level normalization issues (2NF, 3NF, BCNF)
  without access to actual data and functional dependency declarations.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from engine.errors import MigrationError
from engine.schema import SchemaSnapshot


# ── Severity ─────────────────────────────────────────────────────────────────

class Severity(Enum):
    MEDIUM = "MEDIUM"


# ── Violation dataclass ───────────────────────────────────────────────────────

@dataclass
class NamingViolation:
    """
    A single heuristic warning produced by the naming analysis phase.

    Attributes:
        table:      The table containing the anomaly.
        column:     The column involved, or None if the check is table-level.
        check_name: A short human-readable name for the heuristic rule.
        detail:     A full human-readable explanation of the anomaly.
        severity:   Always MEDIUM — naming heuristics are advisory by design.
    """
    table: str
    check_name: str
    detail: str
    column: str | None = field(default=None)
    severity: Severity = field(default=Severity.MEDIUM)


# ── Regex patterns for column name heuristics ─────────────────────────────────

# Columns whose names suggest they might store multiple values (arrays/CSV).
# These patterns are conservative — only flag names that strongly suggest
# list-storage semantics.
_ARRAY_COLUMN_PATTERN = re.compile(
    r"(_ids|_list|_csv|_array|_values|s_str)$",
    re.IGNORECASE,
)

# Columns whose names suggest a FK reference to another table.
# e.g. `user_id` -> likely references `users` or `user`.
_FK_REFERENCE_PATTERN = re.compile(r"^(.+)_id$", re.IGNORECASE)


# ── Individual heuristic checks ───────────────────────────────────────────────

def _check_id_columns_without_fk(
    snapshot: SchemaSnapshot,
) -> list[NamingViolation]:
    """
    Find columns named `<something>_id` that do not have a FK constraint.

    RATIONALE: An `_id` suffix is the de facto convention for FK columns.
    A column named `user_id` with no FK to `users` is likely a normalization
    mistake — the developer forgot to declare the FK constraint.

    LIMITATION: Some `_id` columns are legitimately non-FK (e.g. `external_id`,
    `tracking_id`). The heuristic will flag these. Use judgment.
    """
    violations: list[NamingViolation] = []

    for table_name, table in snapshot.tables.items():
        # Collect all source columns that ARE covered by a FK constraint.
        fk_covered_columns: set[str] = {
            fk.from_column for fk in table.foreign_keys
        }

        for col_name in table.columns:
            # Skip the table's own PK (often named 'id' — not a FK reference).
            if col_name == "id":
                continue

            match = _FK_REFERENCE_PATTERN.match(col_name)
            if match and col_name not in fk_covered_columns:
                referenced_entity = match.group(1)
                violations.append(NamingViolation(
                    table=table_name,
                    column=col_name,
                    check_name="Orphaned _id column (missing FK)",
                    detail=(
                        f"Column '{table_name}.{col_name}' looks like a foreign key "
                        f"reference to '{referenced_entity}' but has no FK constraint declared. "
                        f"If this is intentional, consider renaming the column to avoid confusion."
                    ),
                ))

    return violations


def _check_junction_tables_without_composite_pk(
    snapshot: SchemaSnapshot,
) -> list[NamingViolation]:
    """
    Detect tables that pattern-match as junction/join tables but lack a
    composite PRIMARY KEY.

    HEURISTIC: A table whose name contains '_' and has exactly 2 FK columns
    is likely a many-to-many join table. Such tables should use a composite PK
    on the two FK columns to prevent duplicate associations.

    EXAMPLE: `user_roles` with user_id FK and role_id FK should have
    PRIMARY KEY (user_id, role_id). Without it, a user can be assigned
    the same role multiple times.

    LIMITATION: This may fire on non-junction tables that happen to have
    exactly two FKs and an underscore in their name.
    """
    violations: list[NamingViolation] = []

    for table_name, table in snapshot.tables.items():
        # Only consider tables with an underscore in the name (naming convention signal).
        if "_" not in table_name:
            continue

        fk_columns = {fk.from_column for fk in table.foreign_keys}

        # Exactly 2 FK columns and no PK: classic unkeyed junction table.
        if len(fk_columns) == 2 and not table.primary_key_columns:
            cols = ", ".join(sorted(fk_columns))
            violations.append(NamingViolation(
                table=table_name,
                check_name="Junction table missing composite PK",
                detail=(
                    f"Table '{table_name}' appears to be a many-to-many join table "
                    f"(has 2 FK columns: {cols}) but has no PRIMARY KEY. "
                    f"Without a composite PK on ({cols}), duplicate associations are possible."
                ),
            ))

    return violations


def _check_array_named_columns(
    snapshot: SchemaSnapshot,
) -> list[NamingViolation]:
    """
    Flag columns whose names suggest they might be storing multiple values
    in a single field (1NF violation signal).

    RATIONALE: Names like `tag_ids`, `category_list`, `csv_values` are strong
    signals that a developer is storing a delimited list in a text/varchar
    column instead of using a proper junction table.

    LIMITATION: The actual column type is not checked here (it's normalized
    away in SchemaSnapshot). A JSONB column named `tag_ids` is a legitimate
    pattern in Postgres. This heuristic is intentionally coarse.
    """
    violations: list[NamingViolation] = []

    for table_name, table in snapshot.tables.items():
        for col_name in table.columns:
            if _ARRAY_COLUMN_PATTERN.search(col_name):
                violations.append(NamingViolation(
                    table=table_name,
                    column=col_name,
                    check_name="Column name suggests array/CSV storage",
                    detail=(
                        f"Column '{table_name}.{col_name}' name pattern ('{col_name}') "
                        f"suggests it may store multiple values in a single field. "
                        f"Consider using a junction table or a proper array/JSONB column "
                        f"with explicit type constraints."
                    ),
                ))

    return violations


# ── Aggregator ────────────────────────────────────────────────────────────────

def _run_all_heuristics(snapshot: SchemaSnapshot) -> list[NamingViolation]:
    """
    Run all naming heuristic checks and return the combined list of violations.

    Adding a new heuristic: implement a function matching the signature
        _check_<name>(snapshot: SchemaSnapshot) -> list[NamingViolation]
    and append a call to it here.
    """
    violations: list[NamingViolation] = []
    violations.extend(_check_id_columns_without_fk(snapshot))
    violations.extend(_check_junction_tables_without_composite_pk(snapshot))
    violations.extend(_check_array_named_columns(snapshot))
    return violations


# ── Public entry point ────────────────────────────────────────────────────────

class NamingHeuristicError(MigrationError):
    """
    Raised when naming heuristics detect MEDIUM violations in strict mode.
    Inherits from MigrationError so cli.py catches it in the same handler.
    """
    pass


def run_naming_heuristics(
    snapshot: SchemaSnapshot,
    strict: bool = False,
) -> None:
    """
    Run all naming heuristic checks against the schema snapshot.

    - In non-strict mode: prints warnings, exits normally (exit 0).
    - In strict mode: raises NamingHeuristicError (exit 1).

    WHY VOID RETURN: Like run_schema_validation, we either succeed silently
    or raise. The CLI orchestrator does not need to inspect a return value.
    """
    violations = _run_all_heuristics(snapshot)

    if not violations:
        return

    for v in violations:
        loc = f"'{v.table}.{v.column}'" if v.column else f"'{v.table}'"
        print(
            f"  [NAMING WARNING] [{v.severity.value}] Table/column {loc} — {v.check_name}\n"
            f"    Detail: {v.detail}"
        )

    if strict:
        raise NamingHeuristicError(
            f"\nNAMING HEURISTIC CHECK FAILED: {len(violations)} violation(s) detected [strict mode].\n"
            f"Resolve the above structural naming anomalies before deploying to production."
        )
