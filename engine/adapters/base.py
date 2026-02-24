"""
    The tools evaluates the syntax and ordering of the migrations
    but cannot override the DB engine semantics
"""


from abc import ABC, abstractmethod
from typing import Iterable

from engine.models import Migration


class DatabaseAdapter(ABC):
    """
    Abstract database adapter.
    Each database implementation must handle:
    - connection lifecycle
    - per-migration transaction execution
    """

    @abstractmethod
    def execute_migrations(self, migrations: Iterable[Migration]) -> None:
        pass