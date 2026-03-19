#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SafeDB-CI Demo Database Reset
# Usage: bash guide/reset_db.sh
#
# Run this between demo scenarios to wipe all tables and lockfiles so each
# safedb validate command starts from a completely clean state.
# ─────────────────────────────────────────────────────────────────────────────

set -e

# ── Credentials (matches .env) ────────────────────────────────────────────────
PG_USER="${POSTGRES_USER:-safedb}"
PG_PASS="${POSTGRES_PASSWORD:-safedbpass}"
PG_DB="${POSTGRES_DB:-safedb_test}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"

MY_USER="${MYSQL_USER:-safedb}"
MY_PASS="${MYSQL_PASSWORD:-safedbpass}"
MY_DB="${MYSQL_DATABASE:-safedb_test}"
MY_HOST="${MYSQL_HOST:-127.0.0.1}"
MY_PORT="${MYSQL_PORT:-3306}"
MY_ROOT_PASS="${MYSQL_ROOT_PASSWORD:-rootpass}"

echo ""
echo "🔄  Resetting SafeDB-CI demo databases..."
echo ""

# ── 1. Reset PostgreSQL (drop + recreate public schema) ───────────────────────
echo "  [1/3] Resetting PostgreSQL schema..."
PGPASSWORD="$PG_PASS" psql \
  -h "$PG_HOST" \
  -p "$PG_PORT" \
  -U "$PG_USER" \
  -d "$PG_DB" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" \
  -q
echo "         ✅ PostgreSQL wiped."

# ── 2. Reset MySQL (drop + recreate database) ─────────────────────────────────
echo "  [2/3] Resetting MySQL database..."
mysql \
  -h "$MY_HOST" \
  -P "$MY_PORT" \
  -u root \
  -p"$MY_ROOT_PASS" \
  -e "DROP DATABASE IF EXISTS \`$MY_DB\`; CREATE DATABASE \`$MY_DB\`; GRANT ALL ON \`$MY_DB\`.* TO '$MY_USER'@'%';" \
  2>/dev/null
echo "         ✅ MySQL wiped."

# ── 3. Remove all .safedb-lock files from examples directory ──────────────────
echo "  [3/3] Removing lockfiles from examples/..."
find examples/ -name ".safedb-lock" -delete
echo "         ✅ Lockfiles cleaned."

echo ""
echo "✅  Reset complete. All databases are empty and lockfiles cleared."
echo "    You can now run any safedb scenario fresh."
echo ""
