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

    def execute_migrations(self, migrations, dry_run: bool = False) -> None:
        """
        Execute migrations against MySQL.

        ⚠ DRY-RUN LIMITATION FOR MYSQL:
        MySQL issues an implicit COMMIT before and after every DDL statement
        (CREATE TABLE, ALTER TABLE, DROP TABLE, etc.). This means DDL changes
        CANNOT be rolled back even in dry-run mode. The dry-run rollback at the
        end of this method will only undo DML changes (INSERT, UPDATE, DELETE).

        This is a fundamental MySQL engine constraint — not a SafeDB-CI limitation.
        For reliable dry-run behaviour, use PostgreSQL (which supports transactional DDL).

        A warning is printed when dry-run is active on MySQL to make this limitation
        explicit and auditable in CI logs.
        """
        migration_list = list(migrations)

        try:
            conn = mysql.connector.connect(**self.config)
            conn.autocommit = False
            cursor = conn.cursor()

            for migration in migration_list:
                try:
                    sql_text = migration.path.read_text(encoding="utf-8")
                    for statement in sql_text.split(";"):
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)

                    if not dry_run:
                        # Normal mode: commit each migration as it succeeds.
                        conn.commit()
                    else:
                        print(
                            f"  [DRY RUN] v{migration.version} - "
                            f"{migration.filename}: syntax OK "
                            f"(WARNING: DDL may already be committed by MySQL)"
                        )

                except Exception as e:
                    conn.rollback()
                    raise MigrationError(
                        f"MySQL migration failed "
                        f"(v{migration.version} - "
                        f"{migration.filename}): {str(e)}"
                    ) from e

            if dry_run:
                # ⚠ This rollback only affects DML — DDL already committed implicitly.
                conn.rollback()
                print(
                    f"[DRY RUN] {len(migration_list)} migration(s) processed on MySQL.\n"
                    f"WARNING: DDL statements (CREATE TABLE, ALTER TABLE, etc.) cannot be\n"
                    f"rolled back in MySQL. They were committed implicitly. "
                    f"For true dry-run, use PostgreSQL."
                )

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