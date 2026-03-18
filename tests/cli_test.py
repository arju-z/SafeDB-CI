import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

from engine.adapters.mysql import MySQLAdapter
from engine.adapters.postgres import PostgresAdapter
from engine.errors import MigrationError
from engine.executor import execute_migrations
from engine.safety import run_safety_check
from engine.schema import introspect_schema, run_schema_validation
from engine.versioning import load_migrations


console = Console()


# UI
def print_banner():
    banner = r"""
   _____       ____     ____  ____   ____ ___ 
  / ___/____ _/ __/__  / __ \/ __ ) / __ \__ \ 
  \__ \/ __ `/ /_/ _ \/ / / / __  |/ / / /_/ /
 ___/ / /_/ / __/  __/ /_/ / /_/ // /_/ / __/ 
/____/\__,_/_/  \___/_____/_____(_)____/____/  
    """
    console.print(banner, style="bold cyan")
    console.print("SafeDB-CI — Migration Validator\n", style="bold")


#  CLI
def get_parser():
    parser = argparse.ArgumentParser(prog="safedb")

    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--db-type", choices=["postgres", "mysql"], required=True)
    parser.add_argument("--migrations-path", type=Path, required=True)

    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--strict", action="store_true")

    parser.add_argument("--database-url")
    parser.add_argument("--mysql-host")
    parser.add_argument("--mysql-user")
    parser.add_argument("--mysql-password")
    parser.add_argument("--mysql-database")

    # New UX flags
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    return parser



#  DB Adapter

def get_adapter(args):
    if args.db_type == "postgres":
        if args.ci:
            user = os.environ.get("POSTGRES_USER")
            password = os.environ.get("POSTGRES_PASSWORD")
            db = os.environ.get("POSTGRES_DB")

            if not user or not password or not db:
                console.print("[red]Missing PostgreSQL env vars[/red]")
                sys.exit(1)

            url = args.database_url or f"postgresql://{user}:{password}@127.0.0.1:5432/{db}"
            return PostgresAdapter(database_url=url)

        if not args.database_url:
            console.print("[red]--database-url required[/red]")
            sys.exit(1)

        return PostgresAdapter(database_url=args.database_url)

    else:  # mysql
        if args.ci:
            host = args.mysql_host or "127.0.0.1"
            user = args.mysql_user or os.environ.get("MYSQL_USER")
            password = args.mysql_password or os.environ.get("MYSQL_PASSWORD")
            db = args.mysql_database or os.environ.get("MYSQL_DATABASE")

            if not user or not password or not db:
                console.print("[red]Missing MySQL env vars[/red]")
                sys.exit(1)

            return MySQLAdapter(host=host, user=user, password=password, database=db)

        missing = []
        if not args.mysql_host: missing.append("--mysql-host")
        if not args.mysql_user: missing.append("--mysql-user")
        if not args.mysql_password: missing.append("--mysql-password")
        if not args.mysql_database: missing.append("--mysql-database")

        if missing:
            console.print(f"[red]Missing args: {', '.join(missing)}[/red]")
            sys.exit(1)

        return MySQLAdapter(
            host=args.mysql_host,
            user=args.mysql_user,
            password=args.mysql_password,
            database=args.mysql_database,
        )


def build_inspection_conn(args):
    if args.db_type == "postgres":
        import psycopg

        if args.ci:
            user = os.environ.get("POSTGRES_USER")
            password = os.environ.get("POSTGRES_PASSWORD")
            db = os.environ.get("POSTGRES_DB")
            url = args.database_url or f"postgresql://{user}:{password}@127.0.0.1:5432/{db}"
        else:
            url = args.database_url

        return psycopg.connect(url)

    else:
        import mysql.connector
        return mysql.connector.connect(
            host=args.mysql_host or "127.0.0.1",
            user=args.mysql_user or os.environ.get("MYSQL_USER"),
            password=args.mysql_password or os.environ.get("MYSQL_PASSWORD"),
            database=args.mysql_database or os.environ.get("MYSQL_DATABASE"),
        )



# PIPELINE

def run_pipeline(args):
    step = 1

    def step_print(msg):
        if not args.quiet:
            console.print(f"[yellow][{step}/5][/yellow] {msg}", end="")

    def step_done(extra=""):
        nonlocal step
        if not args.quiet:
            console.print(f" .......... [green]✓[/green] {extra}")
        step += 1

    # 1. Load migrations
    step_print("Loading migrations")
    if not args.migrations_path.exists():
        console.print(f"[red]Path not found:[/red] {args.migrations_path}")
        sys.exit(1)

    migrations = load_migrations(args.migrations_path)
    step_done(f"({len(migrations)} found)")

    if args.verbose:
        for m in migrations:
            console.print(f"  → {m.name}")

    # 2. Safety
    step_print("Safety analysis")
    try:
        run_safety_check(migrations)
        step_done()
    except MigrationError as e:
        console.print(" .......... [red]✗[/red]")
        console.print(f"\n[bold red]FAILED:[/bold red]\n{e}")
        sys.exit(1)

    # 3. Execution
    if args.dry_run:
        step_print("Execution skipped")
        step_done("(dry-run)")
        console.print("\n[bold yellow]✔ Dry run complete[/bold yellow]")
        return

    adapter = get_adapter(args)

    step_print("Executing migrations")
    execute_migrations(migrations, adapter)
    step_done()

    # 4. Introspection
    step_print("Schema introspection")
    conn = build_inspection_conn(args)
    try:
        schema = introspect_schema(args.db_type, conn)
    finally:
        conn.close()
    step_done(f"({len(schema.tables)} tables)")

    # 5. Validation
    step_print("Schema validation")
    run_schema_validation(schema, strict=args.strict)
    step_done()

    console.print(f"\n[bold green]✔ Success ({len(migrations)} migrations)[/bold green]")


# ENTRY
def main():
    print_banner()
    parser = get_parser()
    args = parser.parse_args()

    try:
        run_pipeline(args)
        sys.exit(0)

    except MigrationError as e:
        console.print(f"\n[bold red]MIGRATION FAILED[/bold red]\n{e}")
        sys.exit(1)

    except Exception as e:
        console.print(f"\n[bold red]CRITICAL ERROR[/bold red]\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()