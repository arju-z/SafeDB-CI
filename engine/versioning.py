import re
from pathlib import Path
from typing import List

from engine.models import Migration
from engine.errors import ( 
    MigrationError,
    NonSequentialMigrationVersionError,
    InvalidMigrationFilenameError,
    DuplicateMigrationVersionError,
    EmptyMigrationSetError
)

_MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")

def load_migrations(migration_dir : Path) -> List[Migration]:
    """
        Load, Validate and deterministically order migrations

        ONLY FOR ENTERING MIGRATIONS!! DO NOT CHANGE!!

        :param migrations_dir: Path to directory containing SQL migrations
        :return: Ordered list of Migration objects
        :raises MigrationError: if any validation rule is violated
    """

    if not migration_dir.exists() or not migration_dir.is_dir():
        raise EmptyMigrationSetError()
    
    migrations : List[Migration] = []

    for entry in migration_dir.iterdir():
        if not entry.isfile():
            continue
        if entry.suffix != ".sql":
            continue

        match = _MIGRATION_PATTERN.match(entry.name)
        if not match:
            raise InvalidMigrationFilenameError(entry.name)
        
        version = match.group[1]

        migrations.append(
            Migration(
                version=version,
                filename=entry.name,
                path = entry.resolve(),
            )
        )

    if not migrations:
        raise EmptyMigrationSetError()

