from typing import Iterable

from engine.models import Migration
from engine.adapters.base import DatabaseAdapter


def execute_migrations(
    migrations: Iterable[Migration],
    adapter: DatabaseAdapter,
) -> None:
    """
    Orchestrates migration execution using the provided adapter.
    Adapter has an abstract class
    """
    adapter.execute_migrations(migrations)