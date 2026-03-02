# tests/test_versioning.py
import pytest
from pathlib import Path
from engine.versioning import load_migrations
from engine.errors import EmptyMigrationSetError, InvalidMigrationFilenameError

def test_load_migrations_success(tmp_path):
    # Create valid migration files
    (tmp_path / "001_init.sql").write_text("SELECT 1;")
    (tmp_path / "002_users.sql").write_text("SELECT 1;")
    
    migrations = load_migrations(tmp_path)
    
    assert len(migrations) == 2
    assert migrations[0].version == 1
    assert migrations[1].version == 2
    assert migrations[0].filename == "001_init.sql"

def test_load_migrations_sorting(tmp_path):
    # Create files out of order
    (tmp_path / "002_later.sql").write_text("SELECT 1;")
    (tmp_path / "001_earlier.sql").write_text("SELECT 1;")
    
    migrations = load_migrations(tmp_path)
    
    assert migrations[0].version == 1
    assert migrations[1].version == 2

def test_raises_empty_migration_error(tmp_path):
    with pytest.raises(EmptyMigrationSetError):
        load_migrations(tmp_path)

def test_raises_invalid_filename_error(tmp_path):
    (tmp_path / "wrong_name.sql").write_text("SELECT 1;")
    with pytest.raises(InvalidMigrationFilenameError):
        load_migrations(tmp_path)