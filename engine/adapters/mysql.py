import mysql.connector

from engine.adapters.base import DatabaseAdapter
from engine.errors import MigrationError
from engine.models import Migration


class MySQLAdapter(DatabaseAdapter):
    def __init__(self, host, user, password, database):
        self.config = {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
        }

    def execute_migrations(self, migrations):
        try:
            conn = mysql.connector.connect(**self.config)
            conn.autocommit = False
            cursor = conn.cursor()

            for migration in migrations:
                try:
                    sql_text = migration.path.read_text(encoding="utf-8")
                    for statement in sql_text.split(";"):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    conn.commit()

                except Exception as e:
                    conn.rollback()
                    raise MigrationError(
                        f"MySQL migration failed "
                        f"(v{migration.version} - "
                        f"{migration.filename}): {str(e)}"
                    ) from e

        except Exception as connection_error:
            raise MigrationError(
                f"MySQL connection failure: "
                f"{str(connection_error)}"
            ) from connection_error

        finally:
            try:
                cursor.close()
                conn.close()
            except Exception:
                pass