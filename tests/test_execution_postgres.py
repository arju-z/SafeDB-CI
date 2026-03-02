# tests/test_postgres.py
import pytest
from unittest.mock import MagicMock, patch
from engine.adapters.postgres import PostgresAdapter
from engine.errors import MigrationError

@patch("psycopg.connect")
def test_postgres_execute_success(mock_connect):
    # Setup mocks
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn
    
    adapter = PostgresAdapter("postgresql://user:pass@localhost/db")
    migration = MagicMock(version=1, filename="01_test.sql")
    migration.path.read_text.return_value = "CREATE TABLE test;"
    
    adapter.execute_migrations([migration])
    
    # Verify autocommit is off for manual transaction control
    assert mock_conn.autocommit is False
    mock_conn.transaction.assert_called()

@patch("psycopg.connect")
def test_postgres_connection_failure(mock_connect):
    mock_connect.side_effect = Exception("Conn Failed")
    adapter = PostgresAdapter("invalid_url")
    
    with pytest.raises(MigrationError, match="Postgres connection failure"):
        adapter.execute_migrations([MagicMock()])