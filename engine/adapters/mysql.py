"""
    Unlike postgres, mysql commits DDL commands instantly
    So even if the transaction fais, we have to manually
    see where it went wrong
"""

import mysql.connector

from engine.models import Migration
from engine.errors import MigrationError
from engine.adapters.base import DatabaseAdapter


class MySQLAdapter(DatabaseAdapter):
    # Constructor initializes host(localhost), user, password, database(name)
    def __init__(self, host, user, password, database):
        self.config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
        }

    # Overloading the base class function
    def execute_migrations(self, migrations):
        conn = mysql.connector.connect(**self.config)
        try:
            cursor = conn.cursor()
            for migration in migrations:
                try:
                    sql = migration.path.read_text(encoding="utf-8")
                    cursor.execute(sql)
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise MigrationError(
                        f"MySQL migration failed "
                        f"(v{migration.version} - {migration.filename}): {str(e)}"
                    )
        finally:
            cursor.close()
            conn.close()