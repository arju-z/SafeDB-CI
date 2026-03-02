from typing import Iterable

from engine.adapters.base import DatabaseAdapter
from engine.models import Migration


def execute_migrations(
    migrations: Iterable[Migration],
    adapter: DatabaseAdapter,
) -> None:
    """
    Orchestrates migration execution using the provided adapter.
    Adapter has an abstract class
    """
    adapter.execute_migrations(migrations)
