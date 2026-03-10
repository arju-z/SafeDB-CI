from typing import Iterable

from engine.adapters.base import DatabaseAdapter
from engine.models import Migration


def execute_migrations(
    migrations: Iterable[Migration],
    adapter: DatabaseAdapter,
    dry_run: bool = False,
) -> None:
    """
    Orchestrates migration execution using the provided adapter.

    When dry_run=True, migrations are executed inside a transaction that is
    explicitly rolled back at the end. SQL syntax and constraint errors are
    still caught (Phase 3 still validates), but no state is committed to the DB.

    WHY DRY-RUN AT EXECUTOR LEVEL (not adapter level): The executor owns the
    orchestration contract. The adapter owns DB-specific connection semantics.
    The dry_run flag is passed through so the adapter can choose the right
    rollback strategy for its database engine.
    """
    adapter.execute_migrations(migrations, dry_run=dry_run)
