import argparse
import sys
from pathlib import Path

from engine.adapters.mysql import MySQLAdapter
from engine.adapters.postgres import PostgresAdapter
from engine.errors import MigrationError
from engine.executor import execute_migrations
from engine.versioning import load_migrations


def get_parser() -> argparse.ArgumentParser:
    """
    Constructs the CLI parser.
    WHY: Explicitly defining arguments allows the standard library to handle type
    coercion (like Paths) and base-level missing argument errors before our business logic runs.
    """
    parser = argparse.ArgumentParser(
        description="SafeDB-CI: Production database migration validator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--db-type",
        type=str,
        choices=["postgres", "mysql"],
        required=True,
        help="Target database engine (postgres or mysql).",
    )
    
    parser.add_argument(
        "--migrations-path",
        type=Path,
        required=True,
        help="Path to the directory containing SQL migration files.",
    )

    # Postgres specific argument
    # WHY: We don't mark these as 'required=True' at the argparse level because
    # they are mutually exclusive depending on --db-type. We enforce them later.
    parser.add_argument(
        "--database-url",
        type=str,
        help="PostgreSQL connection string (required if --db-type=postgres).",
    )

    # MySQL specific arguments
    parser.add_argument(
        "--mysql-host",
        type=str,
        help="MySQL host address (required if --db-type=mysql).",
    )
    parser.add_argument(
        "--mysql-user",
        type=str,
        help="MySQL user (required if --db-type=mysql).",
    )
    parser.add_argument(
        "--mysql-password",
        type=str,
        help="MySQL password (required if --db-type=mysql).",
    )
    parser.add_argument(
        "--mysql-database",
        type=str,
        help="MySQL database name (required if --db-type=mysql).",
    )

    return parser


def validate_args_and_get_adapter(args: argparse.Namespace):
    """
    Validates the parsed arguments based on engine type and instantiates 
    the correct database adapter.
    
    WHY: Argparse handles semantic parsing, but this function enforces logical 
    combinations. If a user sets --db-type=postgres but forgets --database-url,
    we catch it here defensively before interacting with the database layer.
    """
    if args.db_type == "postgres":
        if not args.database_url:
            # We print directly to stderr and exit here to give user immediate feedback
            # about missing constraints for their specific db type choice.
            print("ERROR: --database-url is required when --db-type=postgres", file=sys.stderr)
            sys.exit(1)
            
        return PostgresAdapter(database_url=args.database_url)

    elif args.db_type == "mysql":
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


def main():
    """
    The main boundary layer between the operating system (CI system) 
    and the migration engine. 
    
    WHY: Handles setup, delegates to business logic, and catches domain exceptions, 
    mapping them securely to Unix exit codes without leaking python stack traces.
    """
    parser = get_parser()
    args = parser.parse_args()

    # 1. Validate Combinations & Setup Adapter
    # WHY: We establish the target database early so we can fail fast
    # before wasting I/O cycles reading migration files.
    adapter = validate_args_and_get_adapter(args)

    # 2. Load Migrations
    # WHY: Load and validate local disk state. If files are missing or out of order,
    # load_migrations raises a MigrationError which we catch strictly below.
    try:
        if not args.migrations_path.exists():
            print(f"ERROR: Migrations directory not found: {args.migrations_path}", file=sys.stderr)
            sys.exit(1)

        print(f"Loading migrations from {args.migrations_path}...")
        migrations = load_migrations(args.migrations_path)
        print(f"Successfully loaded {len(migrations)} migrations.")

        # 3. Execute Pipeline
        print(f"Executing migrations against {args.db_type}...")
        execute_migrations(migrations, adapter)
        
        print(f"SUCCESS: All {len(migrations)} migrations applied.")
        # Explicit exit zero (Standard Unix success signal used by Github Actions)
        sys.exit(0)

    except MigrationError as e:
        # WHY Catch MigrationError: This is our expected failure domain error. 
        # (e.g., Syntax errors in SQL, missing sequence, DB connection dropped)
        # We print only the error message, NOT the stack trace. 
        # In CI, a stack trace is noise. The user needs to know *what* failed (e.g. Migration 002), 
        # not which line in psycopg logic threw the error.
        print(f"\nMIGRATION FAILED:\n{str(e)}", file=sys.stderr)
        
        # Explicitly exit 1 to trigger CI pipeline failure (red X in GitHub Actions)
        sys.exit(1)
        
    except Exception as e:
        # WHY Catch generic Exception: Defensive programming. If an unforeseen error 
        # (like an OS memory error, or stdlib failure) breaches our domain walls, 
        # we catch it to ensure the CI pipeline still halts with a non-zero exit code.
        print(f"\nCRITICAL UNHANDLED SYSTEM ERROR:\n{str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
