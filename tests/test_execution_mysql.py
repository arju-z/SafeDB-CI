# tests/test_mysql.py
import pytest
from unittest.mock import MagicMock, patch
from engine.adapters.mysql import MySQLAdapter
from engine.errors import MigrationError

@patch("mysql.connector.connect")
def test_mysql_execute_success(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn
    
    adapter = MySQLAdapter("host", "user", "pass", "db")
    migration = MagicMock(version=1, filename="01_test.sql")
    migration.path.read_text.return_value = "CREATE TABLE test;"
    
    adapter.execute_migrations([migration])
    
    mock_conn.commit.assert_called()
    assert mock_conn.autocommit is False

@patch("mysql.connector.connect")
def test_mysql_rollback_on_error(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn
    mock_cursor = mock_conn.cursor.return_value
    mock_cursor.execute.side_effect = Exception("SQL Error")
    
    adapter = MySQLAdapter("host", "user", "pass", "db")
    migration = MagicMock(version=1, filename="01_test.sql")
    
    with pytest.raises(MigrationError, match="MySQL migration failed"):
        adapter.execute_migrations([migration])
    
    mock_conn.rollback.assert_called()