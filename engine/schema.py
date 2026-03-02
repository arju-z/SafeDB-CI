"""
engine/schema.py

WHY THIS MODULE EXISTS:
Execution success ≠ Structural correctness.

A migration set that creates a table with a FOREIGN KEY referencing a column
that doesn't exist in the target table, or referencing a non-unique column,
may still appear to "execute" if the DB engine defers constraint checking.
Even when the DB enforces it, the error surfaces as a runtime exception — not
a structural analysis. This module closes that gap by directly introspecting
the database catalog *after* all migrations have been applied and validating
the structural integrity of the resulting schema as a first-class check.

WHY DB-AGNOSTIC NORMALIZED OUTPUT:
PostgreSQL and MySQL store schema metadata in different catalog tables with
different column names, quoting rules, and join strategies. However, the
structural rules we enforce (FK references a real table, FK references a
unique column, no duplicate constraints) are database-agnostic concepts.
We isolate the DB-specific query logic here, normalize into dataclasses,
and run all validation against the normalized form. This keeps the validation
rules pure and lets us add SQLite or MSSQL support later without touching
the validators.

WHY NOT A FULL DIFF ENGINE:
A diff engine requires a "source of truth" schema (e.g. production DB, ORM
models, or a versioned schema file) and compares it to the current state.
We don't have a source of truth here. We validate internal self-consistency:
does the schema that WAS applied make sense as a relational structure on its
own? That is a well-scoped, deterministic check we can make reliably.

KNOWN LIMITATIONS — See bottom of file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from engine.errors import MigrationError


# ---------------------------------------------------------------------------
# SCHEMA DATA MODEL (DB-agnostic normalized representation)
# ---------------------------------------------------------------------------

@dataclass
class ColumnInfo:
    """
    Represents a single column in a table.
    
    WHY A DATACLASS: We want a typed, inspectable in-memory structure —
    not a raw tuple from a cursor. This makes validation code readable.
    """
    name: str
    data_type: str        # Normalized SQL type string, e.g. "integer", "varchar"
    is_nullable: bool     # True if column allows NULL


@dataclass
class ForeignKeyInfo:
    """
    Represents a single foreign key constraint.
    
    WHY STORE BOTH NAMES AND COLUMN REFERENCES:
    When validating, we need to resolve whether:
      - The referenced table exists in the schema.
      - The referenced column exists in that table.
      - The referenced column is part of a primary key or unique constraint.
    Storing all four primitives here allows the validators to work from
    a single object without re-querying the DB.
    """
    constraint_name: str      # The actual constraint name in the DB catalog
    from_column: str          # Column in the current table that holds the FK
    to_table: str             # Table being referenced
    to_column: str            # Column in the referenced table


@dataclass
class TableSchema:
    """
    Represents the full structural definition of a single table.
    """
    name: str
    columns: Dict[str, ColumnInfo] = field(default_factory=dict)
    # Primary key column names, as a set for O(1) lookup during validation
    primary_key_columns: List[str] = field(default_factory=list)
    # Unique constraint column sets — each entry is a frozenset of column names
    # WHY FROZENSET: Order is not meaningful for uniqueness constraints. A
    # composite unique (a, b) is the same as (b, a). Frozenset handles dedup.
    unique_constraint_columns: List[frozenset] = field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)


@dataclass
class SchemaSnapshot:
    """
    Represents the complete post-migration schema of the database.
    This is the root object passed into all validation functions.
    
    WHY 'Snapshot': This is a point-in-time read of the DB catalog after
    migrations have been applied. It is immutable for the lifetime of the
    validation run.
    """
    tables: Dict[str, TableSchema] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ERROR CLASSIFICATION
# ---------------------------------------------------------------------------

class SchemaIntegrityError(MigrationError):
    """
    Raised when HIGH severity structural integrity violations are detected.
    
    WHY INHERIT FROM MigrationError:
    The CLI already catches MigrationError and maps it cleanly to exit code 1
    without printing a raw Python traceback. We leverage that boundary instead
    of introducing a new exception type that would require changes to the CLI
    catch blocks.
    """
    pass


@dataclass
class SchemaAnomaly:
    """
    Represents a single detected structural problem.
    HIGH anomalies are collected and raised as SchemaIntegrityError.
    MEDIUM anomalies are printed as warnings and execution continues.
    """
    severity: str          # "HIGH" or "MEDIUM"
    check: str             # Human-readable check name
    detail: str            # Specific description of what was found


# ---------------------------------------------------------------------------
# POSTGRESQL INTROSPECTION
# ---------------------------------------------------------------------------

def _introspect_postgres(conn) -> SchemaSnapshot:
    """
    Queries the PostgreSQL catalog to build a normalized SchemaSnapshot.
    
    CATALOG TABLES USED:
    
    1. information_schema.columns
       WHY: Standard SQL layer for column metadata. Works across PG versions.
       Gives us table_name, column_name, data_type, is_nullable.
    
    2. information_schema.table_constraints + key_column_usage
       WHY: Gives us PRIMARY KEY and UNIQUE constraint membership per table.
       We avoid pg_constraint directly here because information_schema joins
       are more readable and portable across minor PG versions.
    
    3. information_schema.referential_constraints + key_column_usage
       WHY: The only reliable cross-version way to derive FK source column,
       target table, and target column in a single normalized join. pg_catalog
       is faster but requires explicit OID resolution which varies by PG version.
    
    NOTE: We restrict all queries to the 'public' schema.
    WHY: Most migrations target public. Multi-schema support is a future feature.
    """
    snapshot = SchemaSnapshot()

    with conn.cursor() as cur:

        # ── 1. Load all columns ──────────────────────────────────────────────
        cur.execute("""
            SELECT
                table_name,
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        for table_name, col_name, data_type, is_nullable in cur.fetchall():
            if table_name not in snapshot.tables:
                snapshot.tables[table_name] = TableSchema(name=table_name)
            snapshot.tables[table_name].columns[col_name] = ColumnInfo(
                name=col_name,
                data_type=data_type,
                is_nullable=(is_nullable == "YES"),
            )

        # ── 2. Load primary key columns ─────────────────────────────────────
        cur.execute("""
            SELECT
                kcu.table_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
            ORDER BY kcu.table_name, kcu.ordinal_position
        """)
        for table_name, col_name in cur.fetchall():
            if table_name in snapshot.tables:
                snapshot.tables[table_name].primary_key_columns.append(col_name)

        # ── 3. Load unique constraints ───────────────────────────────────────
        # WHY: A FK may reference a UNIQUE column even if it's not a PK.
        # We must track both when validating FK target integrity.
        cur.execute("""
            SELECT
                kcu.table_name,
                tc.constraint_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
              AND tc.table_schema = 'public'
            ORDER BY kcu.table_name, tc.constraint_name, kcu.ordinal_position
        """)
        unique_groups: Dict[Tuple[str, str], List[str]] = {}
        for table_name, constraint_name, col_name in cur.fetchall():
            key = (table_name, constraint_name)
            unique_groups.setdefault(key, []).append(col_name)
        for (table_name, _), cols in unique_groups.items():
            if table_name in snapshot.tables:
                snapshot.tables[table_name].unique_constraint_columns.append(frozenset(cols))

        # ── 4. Load foreign keys ────────────────────────────────────────────
        # WHY THIS QUERY: information_schema.referential_constraints gives us
        # the mapping between the FK constraint and the unique constraint it
        # references. Joining to key_column_usage twice (once for source, once
        # for target) gives us the exact column mapping.
        cur.execute("""
            SELECT
                rc.constraint_name,
                kcu_from.table_name   AS from_table,
                kcu_from.column_name  AS from_column,
                kcu_to.table_name     AS to_table,
                kcu_to.column_name    AS to_column
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu_from
                ON rc.constraint_name = kcu_from.constraint_name
                AND rc.constraint_schema = kcu_from.table_schema
            JOIN information_schema.key_column_usage kcu_to
                ON rc.unique_constraint_name = kcu_to.constraint_name
                AND rc.unique_constraint_schema = kcu_to.table_schema
                AND kcu_from.ordinal_position = kcu_to.ordinal_position
            WHERE rc.constraint_schema = 'public'
            ORDER BY rc.constraint_name
        """)
        for constraint_name, from_table, from_column, to_table, to_column in cur.fetchall():
            if from_table in snapshot.tables:
                snapshot.tables[from_table].foreign_keys.append(ForeignKeyInfo(
                    constraint_name=constraint_name,
                    from_column=from_column,
                    to_table=to_table,
                    to_column=to_column,
                ))

    return snapshot


# ---------------------------------------------------------------------------
# MYSQL INTROSPECTION
# ---------------------------------------------------------------------------

def _introspect_mysql(conn) -> SchemaSnapshot:
    """
    Queries the MySQL information_schema catalog to build a normalized SchemaSnapshot.
    
    CATALOG TABLES USED:
    
    1. information_schema.COLUMNS
       WHY: Same conceptual role as Postgres — gives column names, types, nullability.
       MySQL stores the DB name in TABLE_SCHEMA, so we filter by the active database.
    
    2. information_schema.KEY_COLUMN_USAGE + TABLE_CONSTRAINTS
       WHY: Gives us PRIMARY KEY membership per table. MySQL stores all constraint
       types here when joined to TABLE_CONSTRAINTS for the constraint_type filter.
    
    3. information_schema.KEY_COLUMN_USAGE (REFERENCED_TABLE_NAME IS NOT NULL)
       WHY: MySQL's information_schema directly exposes FK references in
       KEY_COLUMN_USAGE via REFERENCED_TABLE_NAME and REFERENCED_COLUMN_NAME.
       This is simpler than PostgreSQL's two-step referential_constraints join.
    
    NOTE: We restrict to the current database using DATABASE().
    """
    snapshot = SchemaSnapshot()

    cursor = conn.cursor()

    # ── 1. Load all columns ──────────────────────────────────────────────────
    cursor.execute("""
        SELECT
            TABLE_NAME,
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """)
    for table_name, col_name, data_type, is_nullable in cursor.fetchall():
        if table_name not in snapshot.tables:
            snapshot.tables[table_name] = TableSchema(name=table_name)
        snapshot.tables[table_name].columns[col_name] = ColumnInfo(
            name=col_name,
            data_type=data_type,
            is_nullable=(is_nullable == "YES"),
        )

    # ── 2. Load primary key columns ──────────────────────────────────────────
    cursor.execute("""
        SELECT
            kcu.TABLE_NAME,
            kcu.COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE kcu
        JOIN information_schema.TABLE_CONSTRAINTS tc
            ON kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            AND kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA
            AND kcu.TABLE_NAME = tc.TABLE_NAME
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
          AND kcu.TABLE_SCHEMA = DATABASE()
        ORDER BY kcu.TABLE_NAME, kcu.ORDINAL_POSITION
    """)
    for table_name, col_name in cursor.fetchall():
        if table_name in snapshot.tables:
            snapshot.tables[table_name].primary_key_columns.append(col_name)

    # ── 3. Load unique constraints ────────────────────────────────────────────
    cursor.execute("""
        SELECT
            kcu.TABLE_NAME,
            kcu.CONSTRAINT_NAME,
            kcu.COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE kcu
        JOIN information_schema.TABLE_CONSTRAINTS tc
            ON kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            AND kcu.TABLE_SCHEMA = tc.TABLE_SCHEMA
            AND kcu.TABLE_NAME = tc.TABLE_NAME
        WHERE tc.CONSTRAINT_TYPE = 'UNIQUE'
          AND kcu.TABLE_SCHEMA = DATABASE()
        ORDER BY kcu.TABLE_NAME, kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
    """)
    unique_groups: Dict[Tuple[str, str], List[str]] = {}
    for table_name, constraint_name, col_name in cursor.fetchall():
        key = (table_name, constraint_name)
        unique_groups.setdefault(key, []).append(col_name)
    for (table_name, _), cols in unique_groups.items():
        if table_name in snapshot.tables:
            snapshot.tables[table_name].unique_constraint_columns.append(frozenset(cols))

    # ── 4. Load foreign keys ────────────────────────────────────────────────
    # WHY DIFFERENT FROM POSTGRES: MySQL's information_schema exposes
    # REFERENCED_TABLE_NAME and REFERENCED_COLUMN_NAME directly on
    # KEY_COLUMN_USAGE rows where REFERENCED_TABLE_NAME IS NOT NULL.
    # No need for the referential_constraints join that Postgres requires.
    cursor.execute("""
        SELECT
            CONSTRAINT_NAME,
            TABLE_NAME,
            COLUMN_NAME,
            REFERENCED_TABLE_NAME,
            REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY CONSTRAINT_NAME, ORDINAL_POSITION
    """)
    for constraint_name, from_table, from_column, to_table, to_column in cursor.fetchall():
        if from_table in snapshot.tables:
            snapshot.tables[from_table].foreign_keys.append(ForeignKeyInfo(
                constraint_name=constraint_name,
                from_column=from_column,
                to_table=to_table,
                to_column=to_column,
            ))

    cursor.close()
    return snapshot


# ---------------------------------------------------------------------------
# PUBLIC INTROSPECTION ENTRYPOINT
# ---------------------------------------------------------------------------

def introspect_schema(db_type: str, conn) -> SchemaSnapshot:
    """
    Routes to the correct DB-specific introspection function.
    
    WHY A ROUTER INSTEAD OF INHERITANCE: We don't need a class hierarchy here.
    The introspection functions are pure data-extraction operations, not objects
    with shared state. A simple string dispatch is explicit and easy to audit.
    
    Args:
        db_type: "postgres" or "mysql" — must match the db_type used for execution.
        conn:    A live database connection (psycopg connection or mysql.connector connection).
    """
    if db_type == "postgres":
        return _introspect_postgres(conn)
    elif db_type == "mysql":
        return _introspect_mysql(conn)
    else:
        # Defensive: db_type is validated by argparse before reaching here,
        # but we guard anyway in case this module is called programmatically.
        raise SchemaIntegrityError(f"Unsupported db_type for schema introspection: {db_type!r}")


# ---------------------------------------------------------------------------
# STRUCTURAL VALIDATION CHECKS
# ---------------------------------------------------------------------------

def _check_fk_references_existing_table(
    schema: SchemaSnapshot,
) -> List[SchemaAnomaly]:
    """
    CHECK: Every FOREIGN KEY must reference a table that exists in the schema.
    
    WHY THIS MATTERS: If a migration creates table A with a FK to table B, but
    the migration that creates table B was not applied (wrong order, missing file),
    the FK may be silently deferred or fail at runtime. We surface it explicitly.
    
    SEVERITY: HIGH. A dangling foreign key reference is a structural defect.
    It will cause constraint failures when data is inserted in production.
    """
    anomalies = []
    for table_name, table in schema.tables.items():
        for fk in table.foreign_keys:
            if fk.to_table not in schema.tables:
                anomalies.append(SchemaAnomaly(
                    severity="HIGH",
                    check="FK references non-existent table",
                    detail=(
                        f"Table '{table_name}': FK constraint '{fk.constraint_name}' "
                        f"references table '{fk.to_table}' which does not exist in the schema."
                    ),
                ))
    return anomalies


def _check_fk_references_existing_column(
    schema: SchemaSnapshot,
) -> List[SchemaAnomaly]:
    """
    CHECK: Every FOREIGN KEY must reference a column that exists in the target table.
    
    WHY THIS MATTERS: A FK can point to a table that exists but reference a column
    that was renamed, dropped in a later migration, or simply mistyped.
    This is a common migration authoring error that causes runtime constraint failures.
    
    SEVERITY: HIGH. A FK referencing a non-existent column is a definitive structural defect.
    """
    anomalies = []
    for table_name, table in schema.tables.items():
        for fk in table.foreign_keys:
            target_table = schema.tables.get(fk.to_table)
            if target_table is None:
                # Already caught by _check_fk_references_existing_table — skip duplicate
                continue
            if fk.to_column not in target_table.columns:
                anomalies.append(SchemaAnomaly(
                    severity="HIGH",
                    check="FK references non-existent column",
                    detail=(
                        f"Table '{table_name}': FK constraint '{fk.constraint_name}' "
                        f"references column '{fk.to_table}.{fk.to_column}' which does not exist."
                    ),
                ))
    return anomalies


def _check_fk_references_unique_or_pk_column(
    schema: SchemaSnapshot,
) -> List[SchemaAnomaly]:
    """
    CHECK: Every FOREIGN KEY must reference a column that is part of a 
    PRIMARY KEY or UNIQUE constraint on the target table.
    
    WHY THIS MATTERS: SQL standards require FK targets to be uniquely identifiable.
    PostgreSQL enforces this at constraint-creation time. MySQL (InnoDB) is more
    permissive — it allows FKs to reference non-unique columns in some configurations,
    which can silently create structural ambiguity and unpredictable JOIN behavior.
    
    SEVERITY: HIGH for this check. Referencing a non-unique column is a relational
    integrity defect regardless of whether the DB engine allowed it.
    """
    anomalies = []
    for table_name, table in schema.tables.items():
        for fk in table.foreign_keys:
            target_table = schema.tables.get(fk.to_table)
            if target_table is None:
                continue  # Already caught earlier

            is_pk_col = fk.to_column in target_table.primary_key_columns
            is_unique_col = any(
                fk.to_column in unique_set
                for unique_set in target_table.unique_constraint_columns
            )

            if not is_pk_col and not is_unique_col:
                anomalies.append(SchemaAnomaly(
                    severity="HIGH",
                    check="FK references non-unique column",
                    detail=(
                        f"Table '{table_name}': FK constraint '{fk.constraint_name}' "
                        f"references '{fk.to_table}.{fk.to_column}' which is neither a "
                        f"PRIMARY KEY nor a UNIQUE-constrained column."
                    ),
                ))
    return anomalies


def _check_duplicate_fk_constraints(
    schema: SchemaSnapshot,
) -> List[SchemaAnomaly]:
    """
    CHECK: No two FOREIGN KEY constraints on the same table should reference
    the same (from_column, to_table, to_column) triple.
    
    WHY THIS MATTERS: Duplicate FK constraints add overhead on writes (the DB
    enforces each independently) and indicate a migration authoring error —
    a migration that was accidentally applied twice or a copy-paste mistake.
    
    WHY NOT JUST CONSTRAINT_NAME: Constraint names can be auto-generated and differ
    between runs. We detect semantic duplicates by comparing the actual column mapping.
    
    SEVERITY: MEDIUM. Duplicate FKs degrade write performance and signal authoring
    errors, but do not necessarily corrupt data immediately.
    """
    anomalies = []
    for table_name, table in schema.tables.items():
        seen: Dict[Tuple[str, str, str], str] = {}  # mapping -> constraint_name
        for fk in table.foreign_keys:
            key = (fk.from_column, fk.to_table, fk.to_column)
            if key in seen:
                anomalies.append(SchemaAnomaly(
                    severity="MEDIUM",
                    check="Duplicate FK constraint",
                    detail=(
                        f"Table '{table_name}': FK constraint '{fk.constraint_name}' "
                        f"duplicates constraint '{seen[key]}' — "
                        f"both map '{fk.from_column}' → '{fk.to_table}.{fk.to_column}'."
                    ),
                ))
            else:
                seen[key] = fk.constraint_name
    return anomalies


def _check_tables_have_primary_keys(
    schema: SchemaSnapshot,
) -> List[SchemaAnomaly]:
    """
    CHECK: Every table should have at least one PRIMARY KEY column defined.
    
    WHY THIS MATTERS: Tables without primary keys:
      - Cannot be reliably referenced by foreign keys.
      - Make row-level replication (e.g. Postgres logical replication, MySQL binlog
        row format) fragile or impossible.
      - Make ORM-based access and deduplication logic ambiguous.
    
    WHY MEDIUM NOT HIGH: A table without a PK is structurally suboptimal but
    may be intentional (e.g. a pure junction log table with composite uniqueness
    enforced at the application layer). We warn rather than block.
    """
    anomalies = []
    for table_name, table in schema.tables.items():
        if not table.primary_key_columns:
            anomalies.append(SchemaAnomaly(
                severity="MEDIUM",
                check="Table missing PRIMARY KEY",
                detail=(
                    f"Table '{table_name}' has no PRIMARY KEY defined. "
                    f"This may cause issues with replication, ORMs, and FK referencing."
                ),
            ))
    return anomalies


# ---------------------------------------------------------------------------
# VALIDATION RUNNER
# ---------------------------------------------------------------------------

def run_schema_validation(schema: SchemaSnapshot, strict: bool = False) -> None:
    """
    Executes all structural validation checks against a normalized SchemaSnapshot.
    
    WHY A SINGLE RUNNER: Calling each check directly from the CLI would expose
    validation internals to the CLI layer. The runner acts as the public API of
    this module — the CLI calls run_schema_validation(snapshot), period.
    
    Behavior:
        - Runs ALL checks even if early ones find violations.
          WHY: We want a complete report so the engineer can fix all issues in one pass.
        - HIGH severity anomalies always raise SchemaIntegrityError (exit 1).
        - MEDIUM severity anomalies:
            If strict=False (default): printed as warnings, execution continues.
            If strict=True:            treated as hard failures, raise SchemaIntegrityError.
          WHY CONFIGURABLE: Development branches need flexibility to stage migrations
          iteratively. Production deploy pipelines should reject any structural debt.
    
    Args:
        schema: A SchemaSnapshot produced by introspect_schema().
        strict: If True, MEDIUM anomalies are also hard failures.
    """
    all_anomalies: List[SchemaAnomaly] = []

    # Run all checks and accumulate results
    all_anomalies += _check_fk_references_existing_table(schema)
    all_anomalies += _check_fk_references_existing_column(schema)
    all_anomalies += _check_fk_references_unique_or_pk_column(schema)
    all_anomalies += _check_duplicate_fk_constraints(schema)
    all_anomalies += _check_tables_have_primary_keys(schema)

    high_anomalies = [a for a in all_anomalies if a.severity == "HIGH"]
    medium_anomalies = [a for a in all_anomalies if a.severity == "MEDIUM"]

    # In strict mode, MEDIUM violations are promoted to blocking failures.
    # In relaxed mode, they are printed as informational warnings.
    if strict:
        # Promote all MEDIUM anomalies to the high list so they are included in the error report.
        high_anomalies += medium_anomalies
        medium_anomalies = []   # Nothing left to warn about; all are now blocking.

    # Print remaining MEDIUM warnings immediately so they appear before the raise
    for anomaly in medium_anomalies:
        print(f"  [SCHEMA WARNING] [{anomaly.severity}] {anomaly.check}")
        print(f"    Detail: {anomaly.detail}")

    # Collect all blocking anomalies into a single structured error report
    if high_anomalies:
        report_lines = [
            f"\nSCHEMA INTEGRITY CHECK FAILED: {len(high_anomalies)} violation(s) detected"
            + (" [strict mode]" if strict else "") + ".\n"
        ]
        for anomaly in high_anomalies:
            report_lines.append(f"  [{anomaly.severity}] Check: '{anomaly.check}'")
            report_lines.append(f"    Detail: {anomaly.detail}")
            report_lines.append("")

        report_lines.append(
            "The schema produced by these migrations is structurally inconsistent.\n"
            "Resolve the above anomalies before deploying to production."
        )
        raise SchemaIntegrityError("\n".join(report_lines))


# ---------------------------------------------------------------------------
# KNOWN LIMITATIONS
# ---------------------------------------------------------------------------
"""
1. NO LOGICAL SCHEMA DIFFING:
   We do not compare the resulting schema to any baseline (production schema,
   expected schema, or ORM model definitions). We only validate internal
   self-consistency of what was applied.

2. NO DATA-LEVEL VALIDATION:
   We cannot detect that a SET NOT NULL constraint will fail because production
   rows already have NULLs. The CI DB is empty. Data-level validation requires
   a production replica or snapshot, which is out of scope.

3. NO DETECTION OF MISSING INTENDED CONSTRAINTS:
   If a developer forgets to add an index or FK entirely, we cannot detect it.
   We only detect structural problems with constraints that DO exist.

4. DIALECT DIFFERENCES:
   MySQL's InnoDB allows FK references to non-unique columns in some non-strict
   configurations. Our check catches this at the validation layer. PostgreSQL
   rejects it at constraint-creation time. The two paths will surface the error
   at different stages, but both will halt the pipeline.

5. THE REGEX SAFETY LAYER REMAINS INDEPENDENT:
   The safety.py static analysis runs BEFORE execution. This module runs AFTER
   execution. They are complementary, not redundant. One detects dangerous intent
   in SQL text; the other validates the structural outcome in the DB catalog.

6. PUBLIC SCHEMA ONLY (POSTGRESQL):
   All PostgreSQL introspection queries filter to table_schema = 'public'.
   Multi-schema PostgreSQL databases are not supported in this version.
"""
