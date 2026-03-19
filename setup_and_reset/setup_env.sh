#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SafeDB-CI Demo Environment Setup
# Run: source guide/setup_env.sh
# Must be SOURCED (not executed) so that variables persist in your shell.
# ─────────────────────────────────────────────────────────────────────────────

# PostgreSQL
export POSTGRES_USER=safedb
export POSTGRES_PASSWORD=safedbpass
export POSTGRES_DB=safedb_test
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

# MySQL
export MYSQL_USER=safedb
export MYSQL_PASSWORD=safedbpass
export MYSQL_DATABASE=safedb_test
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_ROOT_PASSWORD=rootpass

echo "✅  SafeDB-CI environment variables loaded."
echo ""
echo "  PostgreSQL → ${POSTGRES_USER}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
echo "  MySQL      → ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
echo ""
echo "  Ready to run: safedb validate --db-type postgres --ci --migrations-path ./examples/..."
