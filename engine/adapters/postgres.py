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

    def execute_migrations(self, migrations):
        try:
            with psycopg.connect(self.database_url) as conn:
                conn.autocommit = False

                for migration in migrations:
                    try:
                        with conn.transaction():
                            sql_text = migration.path.read_text(
                                encoding="utf-8"
                            )

                            with conn.cursor() as cur:
                                cur.execute(sql_text)

                    except Exception as e:
                        raise MigrationError(
                            f"Postgres migration failed "
                            f"(v{migration.version} - "
                            f"{migration.filename}): {str(e)}"
                        ) from e

        except Exception as connection_error:
            raise MigrationError(
                f"Postgres connection failure: {str(connection_error)}"
            ) from connection_error