import argparse
import os
import sys
from pathlib import Path

from engine.adapters.mysql import MySQLAdapter
from engine.adapters.postgres import PostgresAdapter
from engine.errors import MigrationError
from engine.executor import execute_migrations
from engine.lockfile import check_tamper, load_lockfile, write_lockfile
from engine.naming import NamingHeuristicError, run_naming_heuristics
from engine.reporter import (
    PhaseResult,
    PhaseStatus,
    PipelineReport,
    emit_console_summary,
    emit_github_summary,
    emit_json,
)
from engine.safety import run_safety_check
from engine.schema import introspect_schema, run_schema_validation
from engine.versioning import load_migrations


def get_parser() -> argparse.ArgumentParser:
    """
    Constructs the CLI parser.
    WHY: Explicitly defining arguments allows the standard library to handle type
    coercion (like Paths) and base-level missing argument errors before our business logic runs.
    """
    # RawDescriptionHelpFormatter preserves newlines in the description and epilog,
    # allowing us to write a rich, human-readable help body without argparse collapsing it.
    parser = argparse.ArgumentParser(
        prog="safedb",
        description=(
            "SafeDB-CI — Production Database Migration Validator\n"
            "====================================================\n"
            "\n"
            "Validates SQL migration files against a live database before production deploy.\n"
            "Performs three safety checks in sequence:\n"
            "\n"
            "  1. ORDERING CHECK  — Ensures migrations are numbered sequentially with no gaps\n"
            "                       or duplicate version numbers (e.g. 001_, 002_, 003_).\n"
            "\n"
            "  2. SAFETY ANALYSIS — Statically scans SQL text for destructive operations\n"
            "                       (DROP TABLE, TRUNCATE, DELETE without WHERE, CASCADE, etc.)\n"
            "                       BEFORE any SQL is executed. Blocks HIGH severity violations.\n"
            "                       Warns on MEDIUM severity (ALTER COLUMN TYPE, SET NOT NULL).\n"
            "\n"
            "  3. EXECUTION CHECK — Applies each migration inside an individual transaction\n"
            "                       against a real ephemeral database. Catches syntax errors,\n"
            "                       constraint violations, and type mismatches at runtime.\n"
            "                       PostgreSQL fully rolls back on failure (DDL is transactional).\n"
            "                       MySQL issues an implicit DDL commit — rollback is NOT\n"
            "                       guaranteed for schema changes; see --db-type=mysql notes.\n"
        ),
        epilog=(
            "────────────────────────────────────────────────────────────────\n"
            "EXIT CODES\n"
            "────────────────────────────────────────────────────────────────\n"
            "  0   All checks passed. Migrations are safe to deploy.\n"
            "  1   One or more checks failed. Do NOT deploy. See stderr for details.\n"
            "\n"
            "────────────────────────────────────────────────────────────────\n"
            "MIGRATION FILE NAMING CONVENTION\n"
            "────────────────────────────────────────────────────────────────\n"
            "  Files must follow the exact pattern:  NNN_description.sql\n"
            "  Examples:  001_create_users.sql\n"
            "             002_add_email_index.sql\n"
            "             003_drop_legacy_table.sql   ← will be BLOCKED by safety check\n"
            "\n"
            "  Rules enforced:\n"
            "    - Version number must start at 001 and increment by 1.\n"
            "    - No duplicate version numbers permitted.\n"
            "    - No gaps in the sequence (001, 002, 004 will fail).\n"
            "    - Any .sql file not matching the pattern causes an immediate error.\n"
            "\n"
            "────────────────────────────────────────────────────────────────\n"
            "USAGE EXAMPLES\n"
            "────────────────────────────────────────────────────────────────\n"
            "\n"
            "  # Local validation against PostgreSQL:\n"
            "  safedb validate \\\n"
            "    --db-type postgres \\\n"
            "    --migrations-path ./migrations \\\n"
            "    --database-url \"postgresql://user:pass@127.0.0.1:5432/mydb\"\n"
            "\n"
            "  # Local validation against MySQL:\n"
            "  safedb validate \\\n"
            "    --db-type mysql \\\n"
            "    --migrations-path ./migrations \\\n"
            "    --mysql-host 127.0.0.1 \\\n"
            "    --mysql-user myuser \\\n"
            "    --mysql-password mypass \\\n"
            "    --mysql-database mydb\n"
            "\n"
            "  # CI mode (credentials from environment variables):\n"
            "  export POSTGRES_USER=myuser\n"
            "  export POSTGRES_PASSWORD=mypass\n"
            "  export POSTGRES_DB=mydb\n"
            "  safedb validate \\\n"
            "    --db-type postgres \\\n"
            "    --ci \\\n"
            "    --migrations-path ./migrations\n"
            "\n"
            "────────────────────────────────────────────────────────────────\n"
            "SAFETY RULES REFERENCE\n"
            "────────────────────────────────────────────────────────────────\n"
            "\n"
            "  HIGH severity  →  Blocks execution immediately. Fix before merging.\n"
            "  ┌─────────────────────────────┬───────────────────────────────────────┐\n"
            "  │ Rule                        │ Why it is dangerous                   │\n"
            "  ├─────────────────────────────┼───────────────────────────────────────┤\n"
            "  │ DROP TABLE                  │ Irrecoverable data loss               │\n"
            "  │ DROP COLUMN                 │ Permanent column and data removal     │\n"
            "  │ TRUNCATE                    │ Deletes all rows, no transaction log  │\n"
            "  │ ALTER TABLE … DROP          │ Drops column without COLUMN keyword   │\n"
            "  │ CASCADE                     │ Silently deletes child FK rows        │\n"
            "  │ DELETE FROM <t> (no WHERE)  │ Full-table wipe, unrecoverable        │\n"
            "  └─────────────────────────────┴───────────────────────────────────────┘\n"
            "\n"
            "  MEDIUM severity  →  Warning printed. Execution continues.\n"
            "  ┌─────────────────────────────┬───────────────────────────────────────┐\n"
            "  │ Rule                        │ Why it warrants review                │\n"
            "  ├─────────────────────────────┼───────────────────────────────────────┤\n"
            "  │ ALTER COLUMN TYPE           │ May silently truncate data on cast    │\n"
            "  │ SET NOT NULL                │ Fails in prod if NULLs exist in table │\n"
            "  └─────────────────────────────┴───────────────────────────────────────┘\n"
            "\n"
            "────────────────────────────────────────────────────────────────\n"
            "POSTGRESQL NOTES\n"
            "────────────────────────────────────────────────────────────────\n"
            "  DDL statements (CREATE TABLE, ALTER TABLE) are fully transactional\n"
            "  in PostgreSQL. A failed migration is completely rolled back, leaving\n"
            "  the database in the exact state it was in before execution began.\n"
            "\n"
            "────────────────────────────────────────────────────────────────\n"
            "MYSQL NOTES  ⚠\n"
            "────────────────────────────────────────────────────────────────\n"
            "  MySQL issues an implicit COMMIT before and after every DDL statement.\n"
            "  This means a failed migration containing DDL CANNOT be fully rolled back.\n"
            "  Any CREATE TABLE, ALTER TABLE, or DROP TABLE that executed before the\n"
            "  failure point will be permanently committed.\n"
            "\n"
            "  Mitigation: Write exactly ONE DDL statement per migration file.\n"
            "  The InnoDB engine must be used (ENGINE=InnoDB). MyISAM has no transactions.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional 'command' argument — enables 'safedb validate ...' syntax.
    # WHY: An explicit command noun is conventional in production CLIs and reserves
    # namespace for future sub-commands (e.g. 'safedb plan', 'safedb rollback').
    parser.add_argument(
        "command",
        choices=["validate"],
        metavar="command",
        help=(
            "The operation to perform.\n"
            "  validate  Run ordering, safety, and execution checks on migrations."
        ),
    )

    parser.add_argument(
        "--db-type",
        type=str,
        choices=["postgres", "mysql"],
        required=True,
        metavar="{postgres,mysql}",
        help=(
            "Target database engine. Required.\n"
            "  postgres  PostgreSQL 12+ (full DDL transaction support).\n"
            "  mysql     MySQL 8+ with InnoDB (DDL is NOT transactional — see notes above)."
        ),
    )

    parser.add_argument(
        "--migrations-path",
        type=Path,
        required=True,
        metavar="PATH",
        help=(
            "Path to the directory containing SQL migration files. Required.\n"
            "Files must be named NNN_description.sql (e.g. 001_create_users.sql).\n"
            "Migrations are loaded and ordered by their numeric prefix.\n"
            "Gaps or duplicate version numbers will cause an immediate validation error."
        ),
    )

    parser.add_argument(
        "--ci",
        action="store_true",
        help=(
            "Enable CI mode. When set, database credentials are automatically read\n"
            "from environment variables instead of requiring explicit CLI arguments.\n"
            "Manual arguments (e.g. --database-url) take precedence if also provided.\n"
            "\n"
            "  PostgreSQL CI env vars:\n"
            "    POSTGRES_USER      Database username\n"
            "    POSTGRES_PASSWORD  Database password\n"
            "    POSTGRES_DB        Database name\n"
            "    Host is fixed to 127.0.0.1, port to 5432.\n"
            "\n"
            "  MySQL CI env vars:\n"
            "    MYSQL_USER         Database username\n"
            "    MYSQL_PASSWORD     Database password\n"
            "    MYSQL_DATABASE     Database name\n"
            "    Host is fixed to 127.0.0.1, port to 3306.\n"
            "\n"
            "Intended for use with GitHub Actions 'services:' containers where the\n"
            "database is spun up by the CI runner and available at 127.0.0.1."
        ),
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Strict mode. When set, MEDIUM severity schema anomalies are treated as\n"
            "hard failures (exit 1) instead of warnings (exit 0).\n"
            "\n"
            "When NOT set (default):\n"
            "  - HIGH severity violations → always block (exit 1).\n"
            "  - MEDIUM severity violations → printed as warnings, exit 0.\n"
            "\n"
            "When set:\n"
            "  - HIGH severity violations → block (exit 1).\n"
            "  - MEDIUM severity violations → also block (exit 1).\n"
            "\n"
            "Use this flag in production deployment pipelines where any structural\n"
            "warning (missing PK, duplicate FK) must be resolved before deploy.\n"
            "Leave it off in development branches to allow iterative migration work."
        ),
    )

    # ── v2: Dry-run mode ────────────────────────────────────────────────────
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Dry-run mode. Validates migration SQL syntax against a real DB without\n"
            "committing any state. Each migration is executed inside a transaction that\n"
            "is explicitly rolled back at the end.\n"
            "\n"
            "Phases 4-6 (introspection, schema validation, lockfile) are skipped\n"
            "because nothing was committed — the catalog is unchanged.\n"
            "\n"
            "⚠ PostgreSQL: full dry-run (all DDL is rolled back).\n"
            "⚠ MySQL: partial dry-run only (DDL auto-commits implicitly)."
        ),
    )

    # ── v2: Structured output ────────────────────────────────────────────────
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        metavar="{text,json}",
        help=(
            "Output format.\n"
            "  text  Human-readable console output (default).\n"
            "  json  Emit a structured JSON report to report.json.\n"
            "        Also writes a Markdown summary to $GITHUB_STEP_SUMMARY\n"
            "        when running inside GitHub Actions."
        ),
    )

    # ── v2: Lockfile path ────────────────────────────────────────────────────
    parser.add_argument(
        "--lockfile-path",
        type=Path,
        default=Path(".safedb-lock"),
        metavar="PATH",
        help=(
            "Path to the migration lockfile (default: .safedb-lock).\n"
            "The lockfile records the SHA-256 hash of each migration file after a\n"
            "successful validation run. On subsequent runs, any change to a previously\n"
            "validated file is treated as a hard error (TAMPER DETECTED).\n"
            "\n"
            "The lockfile should be committed to version control."
        ),
    )

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    parser.add_argument(
        "--database-url",
        type=str,
        metavar="URL",
        help=(
            "[PostgreSQL only] Full connection URL. Required when --db-type=postgres\n"
            "and --ci is NOT active. Ignored when --db-type=mysql.\n"
            "\n"
            "Format:  postgresql://USER:PASSWORD@HOST:PORT/DBNAME\n"
            "Example: postgresql://safedb:secret@127.0.0.1:5432/myapp_test\n"
            "\n"
            "When --ci is also provided, this argument overrides the auto-constructed\n"
            "URL from environment variables, allowing manual override during debugging."
        ),
    )

    # ── MySQL ───────────────────────────────────────────────────────────────
    parser.add_argument(
        "--mysql-host",
        type=str,
        metavar="HOST",
        help=(
            "[MySQL only] Hostname or IP address of the MySQL server.\n"
            "Required when --db-type=mysql and --ci is NOT active.\n"
            "When --ci is active, defaults to 127.0.0.1 if not specified.\n"
            "\n"
            "Example: --mysql-host 127.0.0.1"
        ),
    )
    parser.add_argument(
        "--mysql-user",
        type=str,
        metavar="USER",
        help=(
            "[MySQL only] Username for MySQL authentication.\n"
            "Required when --db-type=mysql and --ci is NOT active.\n"
            "When --ci is active, falls back to the MYSQL_USER environment variable."
        ),
    )
    parser.add_argument(
        "--mysql-password",
        type=str,
        metavar="PASSWORD",
        help=(
            "[MySQL only] Password for MySQL authentication.\n"
            "Required when --db-type=mysql and --ci is NOT active.\n"
            "When --ci is active, falls back to the MYSQL_PASSWORD environment variable.\n"
            "\n"
            "Security note: Passing passwords as CLI arguments may expose them in shell\n"
            "history and process listings. Prefer --ci mode with environment variables\n"
            "in any automated or shared environment."
        ),
    )
    parser.add_argument(
        "--mysql-database",
        type=str,
        metavar="DATABASE",
        help=(
            "[MySQL only] Name of the target MySQL database.\n"
            "Required when --db-type=mysql and --ci is NOT active.\n"
            "When --ci is active, falls back to the MYSQL_DATABASE environment variable."
        ),
    )

    return parser


def validate_args_and_get_adapter(args: argparse.Namespace):
    """
    Validates combinations, integrates environment variables if --ci is active, 
    and instantiates the domain adapter.
    
    WHY: Separating config resolution from the adapter classes keeps the database 
    adapters pure. They don't need to know if they are running in CI or on a laptop; 
    they just receive validated connection primitives.
    """
    if args.db_type == "postgres":
        if args.ci:
            # CI Mode: We fall back to env vars ONLY if the user didn't explicitly manually override
            # WHY: This avoids conflicts and allows manual overrides even in CI mode when debugging logic.
            # We assume host 127.0.0.1 (not "localhost") to bypass Docker IPv6 proxy mapping bugs natively.
            user = os.environ.get("POSTGRES_USER")
            password = os.environ.get("POSTGRES_PASSWORD")
            db = os.environ.get("POSTGRES_DB")

            if not user or not password or not db:
                # WHY Fail Fast: If a CI task is missing a variable, creating an adapter 
                # object is dangerous. We die with a clean Error 1 message here immediately.
                print("ERROR: --ci mode requires POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB environment variables.", file=sys.stderr)
                sys.exit(1)

            # Build URL defensively, but respect manual manual parameter override (--database-url) if it exists
            db_url = args.database_url or f"postgresql://{user}:{password}@127.0.0.1:5432/{db}"
            return PostgresAdapter(database_url=db_url)
        else:
            if not args.database_url:
                print("ERROR: --database-url is required when --db-type=postgres (unless --ci is active)", file=sys.stderr)
                sys.exit(1)
            return PostgresAdapter(database_url=args.database_url)

    elif args.db_type == "mysql":
        if args.ci:
            # Same defensive fallback logic for MySQL. 
            # CLI args take absolute precedence over environment variables.
            host = args.mysql_host or "127.0.0.1"
            user = args.mysql_user or os.environ.get("MYSQL_USER")
            password = args.mysql_password or os.environ.get("MYSQL_PASSWORD")
            database = args.mysql_database or os.environ.get("MYSQL_DATABASE")

            missing = []
            if not user: missing.append("MYSQL_USER env var (or --mysql-user)")
            if not password: missing.append("MYSQL_PASSWORD env var (or --mysql-password)")
            if not database: missing.append("MYSQL_DATABASE env var (or --mysql-database)")

            if missing:
                print(f"ERROR: --ci mode missing required MySQL configuration: {', '.join(missing)}", file=sys.stderr)
                sys.exit(1)

            return MySQLAdapter(host=host, user=user, password=password, database=database)
        else:
            missing = []
            if not args.mysql_host: missing.append("--mysql-host")
            if not args.mysql_user: missing.append("--mysql-user")
            if not args.mysql_password: missing.append("--mysql-password")
            if not args.mysql_database: missing.append("--mysql-database")
            
            if missing:
                print(f"ERROR: Missing required MySQL arguments: {', '.join(missing)}", file=sys.stderr)
                sys.exit(1)
                
            return MySQLAdapter(
                host=args.mysql_host,
                user=args.mysql_user,
                password=args.mysql_password,
                database=args.mysql_database,
            )


def _build_inspection_connection(args: argparse.Namespace):
    """
    Opens a dedicated inspection-only connection for schema introspection.

    WHY A SEPARATE CONNECTION:
    The adapter uses its connection internally for migration execution and
    closes it when done. To introspect schema state AFTER migrations have
    fully committed, we open a fresh connection here in read mode.
    This keeps the adapter layer untouched and schema inspection decoupled.

    WHY NOT REUSE THE ADAPTER'S CONNECTION:
    The PostgresAdapter uses psycopg's context manager which closes the
    connection on exit. By the time schema validation runs, the adapter
    connection is already closed. Opening a new one is the correct design.
    """
    if args.db_type == "postgres":
        import psycopg
        # Reconstruct the same URL that the adapter used; args are already resolved
        if args.ci:
            user = args.database_url and None or os.environ.get("POSTGRES_USER")
            password = os.environ.get("POSTGRES_PASSWORD")
            db = os.environ.get("POSTGRES_DB")
            db_url = args.database_url or f"postgresql://{user}:{password}@127.0.0.1:5432/{db}"
        else:
            db_url = args.database_url
        return psycopg.connect(db_url)

    elif args.db_type == "mysql":
        import mysql.connector
        if args.ci:
            return mysql.connector.connect(
                host=args.mysql_host or "127.0.0.1",
                user=args.mysql_user or os.environ.get("MYSQL_USER"),
                password=args.mysql_password or os.environ.get("MYSQL_PASSWORD"),
                database=args.mysql_database or os.environ.get("MYSQL_DATABASE"),
            )
        else:
            return mysql.connector.connect(
                host=args.mysql_host,
                user=args.mysql_user,
                password=args.mysql_password,
                database=args.mysql_database,
            )


def main():
    """
    Main CLI entry point. Orchestrates the full SafeDB-CI pipeline.

    v2 pipeline:
      Phase 1   — Ordering (versioning.py)
      Phase 1b  — Tamper check (lockfile.py)     [NEW v2]
      Phase 2   — Safety scan (safety.py)
      Phase 3   — Execution (executor.py)        [dry-run support NEW v2]
      Phase 4   — Introspection (schema.py)      [skipped in dry-run]
      Phase 5a  — Structural validation          [skipped in dry-run]
      Phase 5b  — Naming heuristics (naming.py)  [NEW v2, skipped in dry-run]
      Phase 6   — Lockfile write (lockfile.py)   [NEW v2, skipped in dry-run]
      Output    — JSON report + GHA summary      [NEW v2]
    """
    parser = get_parser()
    args = parser.parse_args()

    # Initialise the pipeline report. Populated as phases complete.
    # Emitted at the very end regardless of exit code.
    report = PipelineReport(
        db_type=args.db_type,
        migrations_path=str(args.migrations_path),
        dry_run=args.dry_run,
    )

    def _finish(exit_code: int) -> None:
        """Emit the report and exit with the given code."""
        report.exit_code = exit_code
        if args.output == "json":
            emit_json(report, Path("report.json"))
            emit_console_summary(report)
        emit_github_summary(report)
        sys.exit(exit_code)

    # Adapter setup — fail fast before any file I/O.
    adapter = validate_args_and_get_adapter(args)

    try:
        if not args.migrations_path.exists():
            print(f"ERROR: Migrations directory not found: {args.migrations_path}", file=sys.stderr)
            sys.exit(1)

        # ── Phase 1: Ordering ──────────────────────────────────────────────────
        print(f"Loading migrations from {args.migrations_path}...")
        migrations = load_migrations(args.migrations_path)
        print(f"Successfully loaded {len(migrations)} migrations.")
        report.ordering = PhaseResult(
            status=PhaseStatus.PASS,
            detail=f"{len(migrations)} migration(s) loaded",
        )

        # ── Phase 1b: Tamper check ─────────────────────────────────────────────
        lockfile_data = load_lockfile(args.lockfile_path)
        if lockfile_data is not None:
            tamper_violations = check_tamper(migrations, lockfile_data)
            if tamper_violations:
                report.tamper_check = PhaseResult(
                    status=PhaseStatus.FAIL,
                    detail=f"{len(tamper_violations)} tampered file(s)",
                    extras={"violations": [
                        {"file": v.filename, "rule": "Content changed",
                         "detail": f"expected {v.expected_hash[:16]}... got {v.actual_hash[:16]}...",
                         "severity": "HIGH"}
                        for v in tamper_violations
                    ]},
                )
                print("\nMIGRATION FAILED:\n", file=sys.stderr)
                print("TAMPER DETECTED: The following migration files have been modified "
                      "since last validation:", file=sys.stderr)
                for v in tamper_violations:
                    print(f"  ✗ {v.filename}", file=sys.stderr)
                    print(f"      Expected: {v.expected_hash}", file=sys.stderr)
                    print(f"      Actual:   {v.actual_hash}", file=sys.stderr)
                print("\nEditing committed migrations corrupts database state history."
                      " Write a new migration instead.", file=sys.stderr)
                _finish(1)
            else:
                report.tamper_check = PhaseResult(
                    status=PhaseStatus.PASS, detail="All hashes match"
                )
        else:
            report.tamper_check = PhaseResult(
                status=PhaseStatus.PASS, detail="No lockfile yet (first run)"
            )

        # ── Phase 2: Safety scan ───────────────────────────────────────────────
        print("Running safety analysis...")
        run_safety_check(migrations)
        print("Safety check passed.")
        report.safety = PhaseResult(status=PhaseStatus.PASS)

        # ── Phase 3: Execution ─────────────────────────────────────────────────
        if args.dry_run:
            print(f"[DRY RUN] Validating migrations against {args.db_type} (changes will be rolled back)...")
        else:
            print(f"Executing migrations against {args.db_type}...")

        execute_migrations(migrations, adapter, dry_run=args.dry_run)

        if args.dry_run:
            report.execution = PhaseResult(
                status=PhaseStatus.PASS,
                detail=f"{len(migrations)} migration(s) validated (dry run — rolled back)",
            )
            # Skip phases 4–6: nothing was committed, catalog is unchanged.
            report.introspection = PhaseResult(status=PhaseStatus.SKIPPED, detail="dry-run mode")
            report.structural_validation = PhaseResult(status=PhaseStatus.SKIPPED, detail="dry-run mode")
            report.naming_heuristics = PhaseResult(status=PhaseStatus.SKIPPED, detail="dry-run mode")
            report.lockfile = PhaseResult(status=PhaseStatus.SKIPPED, detail="dry-run mode")
            print(f"\nDRY RUN COMPLETE: All {len(migrations)} migrations validated. No state committed.")
            _finish(0)

        print(f"All {len(migrations)} migrations executed.")
        report.execution = PhaseResult(
            status=PhaseStatus.PASS,
            detail=f"{len(migrations)} migration(s) applied",
        )

        # ── Phase 4: Schema introspection ─────────────────────────────────────
        print("Introspecting post-migration schema...")
        inspection_conn = _build_inspection_connection(args)
        try:
            schema_snapshot = introspect_schema(args.db_type, inspection_conn)
        finally:
            inspection_conn.close()
        print(f"Schema introspection complete. Found {len(schema_snapshot.tables)} table(s).")
        report.introspection = PhaseResult(
            status=PhaseStatus.PASS,
            detail=f"{len(schema_snapshot.tables)} table(s) found",
        )

        # ── Phase 5a: Structural schema validation ────────────────────────────
        print("Running structural schema validation...")
        run_schema_validation(schema_snapshot, strict=args.strict)
        print("Schema validation passed.")
        report.structural_validation = PhaseResult(status=PhaseStatus.PASS)

        # ── Phase 5b: Naming heuristics ───────────────────────────────────────
        print("Running schema naming heuristics...")
        run_naming_heuristics(schema_snapshot, strict=args.strict)
        report.naming_heuristics = PhaseResult(status=PhaseStatus.PASS)

        # ── Phase 6: Write lockfile ───────────────────────────────────────────
        write_lockfile(migrations, args.lockfile_path)
        report.lockfile = PhaseResult(
            status=PhaseStatus.PASS,
            detail=f"{len(migrations)} hashes recorded",
        )

        print(f"\nSUCCESS: All {len(migrations)} migrations applied and schema integrity verified.")
        _finish(0)

    except (MigrationError, NamingHeuristicError) as e:
        # Known domain failure — print message only, no stack trace.
        print(f"\nMIGRATION FAILED:\n{str(e)}", file=sys.stderr)
        # Mark the failing phase in the report based on which exception phase we're in.
        # The report already has whichever phases completed; the rest remain PENDING.
        _finish(1)

    except Exception as e:
        # Defensive catch — unforeseen errors must still exit 1.
        print(f"\nCRITICAL UNHANDLED SYSTEM ERROR:\n{str(e)}", file=sys.stderr)
        _finish(1)


if __name__ == "__main__":
    main()
