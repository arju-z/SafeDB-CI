import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

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

console = Console()

def print_banner():
    banner = r"""
   _____        __      ____  ____   ____ ___ 
  / ___/____ _ / /___  / __ \/ __ ) / __ <  /
  \__ \/ __ `// // _ \/ / / / __  |/ / / / / 
 ___/ / /_/ // //  __/ /_/ / /_/ // /_/ / /  
/____/\__,_//_/ \___/_____/_____(_)____/_/   
    """
    console.print(banner, style="bold cyan")
    console.print("SafeDB-CI — Migration Validator\n", style="bold")


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
        description="SafeDB-CI — Production Database Migration Validator",
    )

    # Positional 'command' argument — enables 'safedb validate ...' syntax.
    # WHY: An explicit command noun is conventional in production CLIs and reserves
    # namespace for future sub-commands (e.g. 'safedb plan', 'safedb rollback').
    parser.add_argument(
        "command",
        choices=["validate"],
        metavar="command",
        help="The operation to perform (e.g., validate)",
    )

    parser.add_argument(
        "--db-type",
        type=str,
        choices=["postgres", "mysql"],
        required=True,
        metavar="{postgres,mysql}",
        help="Target database engine (postgres or mysql)",
    )

    parser.add_argument(
        "--migrations-path",
        type=Path,
        required=True,
        metavar="PATH",
        help="Path to the directory containing SQL migration files",
    )

    parser.add_argument(
        "--ci",
        action="store_true",
        help="Enable CI mode (reads DB credentials from environment variables)",
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat MEDIUM severity schema anomalies as hard failures (exit 1)",
    )

    # ── v2: Dry-run mode ────────────────────────────────────────────────────
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validates syntax without committing state (rolls back transactions)",
    )

    # ── v2: Structured output ────────────────────────────────────────────────
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        metavar="{text,json}",
        help="Output format: text (console) or json (file + GitHub summary)",
    )

    # ── v2: Lockfile path ────────────────────────────────────────────────────
    parser.add_argument(
        "--lockfile-path",
        type=Path,
        default=Path(".safedb-lock"),
        metavar="PATH",
        help="Path to the migration lockfile (default: .safedb-lock)",
    )

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    parser.add_argument(
        "--database-url",
        type=str,
        metavar="URL",
        help="[PostgreSQL only] Full connection URL",
    )

    # ── MySQL ───────────────────────────────────────────────────────────────
    parser.add_argument(
        "--mysql-host",
        type=str,
        metavar="HOST",
        help="[MySQL only] Database host address",
    )
    parser.add_argument(
        "--mysql-user",
        type=str,
        metavar="USER",
        help="[MySQL only] Database username",
    )
    parser.add_argument(
        "--mysql-password",
        type=str,
        metavar="PASSWORD",
        help="[MySQL only] Database password",
    )
    parser.add_argument(
        "--mysql-database",
        type=str,
        metavar="DATABASE",
        help="[MySQL only] Target database name",
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
    print_banner()
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
