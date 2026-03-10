"""
In postgres every command can be wrapped inside
one transaction itself. It's a safety net, we can
roll back whenever the migration fails
"""

import psycopg
from psycopg import sql

from engine.adapters.base import DatabaseAdapter
from engine.errors import MigrationError
from engine.models import Migration


class PostgresAdapter(DatabaseAdapter):
    def __init__(self, database_url: str):
        self.database_url = database_url

    def execute_migrations(self, migrations, dry_run: bool = False) -> None:
        """
        Execute migrations against PostgreSQL.

        Normal mode: each migration runs in its own transaction (COMMIT on success,
        ROLLBACK on failure). A failed migration halts the pipeline.

        Dry-run mode: ALL migrations run inside a single outer transaction that is
        explicitly rolled back at the very end. Syntax and constraint errors are
        still caught — Phase 3 still validates — but the DB is left untouched.

        WHY A SINGLE OUTER TRANSACTION FOR DRY-RUN:
        Each migration's individual `conn.transaction()` block still acts as a
        savepoint within the outer transaction. On the final rollback, ALL changes
        from all migrations are undone atomically. This is possible because
        PostgreSQL DDL is fully transactional.
        """
        # Collect migrations into a list so we can iterate multiple times if needed.
        migration_list = list(migrations)

        try:
            with psycopg.connect(self.database_url) as conn:
                conn.autocommit = False

                for migration in migration_list:
                    try:
                        with conn.transaction():
                            sql_text = migration.path.read_text(encoding="utf-8")
                            with conn.cursor() as cur:
                                cur.execute(sql_text)

                        if dry_run:
                            print(
                                f"  [DRY RUN] v{migration.version} - "
                                f"{migration.filename}: syntax OK (not committed)"
                            )
                        # Normal mode: conn.transaction() already committed above.

                    except Exception as e:
                        raise MigrationError(
                            f"Postgres migration failed "
                            f"(v{migration.version} - {migration.filename}): {str(e)}"
                        ) from e

                # After all migrations execute without error:
                if dry_run:
                    # Roll back everything — no state should have been committed.
                    conn.rollback()
                    print(f"[DRY RUN] All {len(migration_list)} migration(s) validated. Changes rolled back.")
                # In normal mode, conn.transaction() inside the loop committed each migration.

        except Exception as connection_error:
            raise MigrationError(
                f"Postgres connection failure: {str(connection_error)}"
            ) from connection_error