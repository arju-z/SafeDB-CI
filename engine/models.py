# This file contains domain models only
# You wont find any logic in here!
# DO NOT try to add logic in here


from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    """
    Immutable data class for a single sql migration
    """

    version: int
    filename: str
    path: Path
