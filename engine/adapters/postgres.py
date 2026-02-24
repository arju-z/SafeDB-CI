"""
    In postgres every command can be wrapped inside
    one transaction itself. It's a safety net, we can 
    roll back whenever the migration fails
"""

import psycopg

from engine.models import Migration
from engine.errors import MigrationError
from engine.adapters.base import DatabaseAdapter

class PostgresAdapter(DatabaseAdapter):
    # Constructor initializes the database url
    def __init__(self, database_url: str):
        self.database_url = database_url

    # Overloading the funtion from base class
    def execute_migrations(self, migrations):
        with psycopg.connect(self.database_url) as conn:
            for migration in migrations:
                try:
                    with conn.transaction():
                        sql = migration.path.read_text(encoding="utf-8")
                        with conn.cursor() as cur:
                            cur.execute(sql)
                except Exception as e:
                    raise MigrationError(
                        f"Postgres migration failed "
                        f"(v{migration.version} - {migration.filename}): {str(e)}"
                    )
