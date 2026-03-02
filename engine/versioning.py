import re
from pathlib import Path
from typing import List

from engine.errors import (DuplicateMigrationVersionError,
                           EmptyMigrationSetError,
                           InvalidMigrationFilenameError, MigrationError,
                           NonSequentialMigrationVersionError)
from engine.models import Migration

_MIGRATION_PATTERN = re.compile(r"^(\d+)_.*\.sql$")


def load_migrations(migration_dir: Path) -> List[Migration]:
    """
    Load, Validate and deterministically order migrations

    ONLY FOR ENTERING MIGRATIONS!! DO NOT CHANGE!!

    :param migrations_dir: Path to directory containing SQL migrations
    :return: Ordered list of Migration objects
    :raises MigrationError: if any validation rule is violated
    """

    if not migration_dir.exists() or not migration_dir.is_dir():
        raise EmptyMigrationSetError()

    migrations: List[Migration] = []

    for entry in migration_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix != ".sql":
            continue

        match = _MIGRATION_PATTERN.match(entry.name)
        if not match:
            raise InvalidMigrationFilenameError(entry.name)

        version = int(match.group(1))

        migrations.append(
            Migration(
                version=version,
                filename=entry.name,
                path=entry.resolve(),
            )
        )

    if not migrations:
        raise EmptyMigrationSetError()

    ordered = sorted(migrations, key=lambda m: m.version)

    # Check for duplicate version numbers.
    # WHY: Two files with the same numeric prefix (001_foo.sql and 001_bar.sql)
    # represent an ambiguous ordering contract — we cannot know which applies first.
    seen_versions: set[int] = set()
    for m in ordered:
        if m.version in seen_versions:
            raise DuplicateMigrationVersionError(m.filename)
        seen_versions.add(m.version)

    # Check that versions form a consecutive sequence starting at 1.
    # WHY: A gap (001, 002, 004) means 003 was deleted, renamed, or never committed.
    # The production database may be in an state we cannot reason about.
    # We refuse to apply migrations on top of an unknown base.
    for i, m in enumerate(ordered):
        expected = i + 1
        if m.version != expected:
            raise NonSequentialMigrationVersionError(expected, m.version)

    return ordered
