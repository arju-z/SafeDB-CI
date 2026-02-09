class MigrationError(Exception):
    """
    Base class for all migration-related errors.
    """
    pass


class EmptyMigrationSetError(MigrationError):
    """
    Raised when no migration files are found.
    """
    pass

class InvalidMigrationFilenameError(MigrationError):
    """
    Raised when a migration filename does not match the required format.
    """
    def __init__(self, filename: str):
        super().__init__(f"Invalid migration filename: {filename}")


class DuplicateMigrationVersionError(MigrationError):
    """
    Raised when two or more migrations share the same version number.
    """
    def __init__(self, version: int):
        super().__init__(f"Duplicate migration version detected: {version}")


class NonSequentialMigrationVersionError(MigrationError):
    """
    Raised when migration versions are not strictly sequential.
    """
    def __init__(self, expected: int, found: int):
        super().__init__(
            f"Non-sequential migration versions: expected {expected}, found {found}"
        )