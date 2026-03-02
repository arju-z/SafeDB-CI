<div align="center">

    # 🛡️ SafeDB-CI

    **Production-grade database migration validator for GitHub Actions.**

    Catch destructive SQL, structural schema defects, and ordering violations _before_ they reach production.

    [![GitHub
    Actions](https://img.shields.io/badge/GitHub_Actions-composite_action-2088FF?logo=github-actions&logoColor=white)](https://github.com/arju-z/SafeDB-CI)
    [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
    [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-12%2B-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
    [![MySQL](https://img.shields.io/badge/MySQL-8%2B-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
    [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## Why SafeDB-CI?

Most CI pipelines verify that migrations _run_. SafeDB-CI verifies that they are _safe_.

A migration that applies cleanly on an empty CI database can still:

- **Drop production data** — `TRUNCATE`, `DROP TABLE`
- **Wipe tables** — `DELETE FROM` without a `WHERE`
- **Delete child rows silently** — `ON DELETE CASCADE` on the wrong table
- **Break relational integrity** — FK referencing a non-unique column
- **Corrupt state in MySQL** — DDL auto-commits; a failed migration cannot roll back

SafeDB-CI runs a **6-phase guardrail pipeline** to catch these issues before your deploy button is pressed.

---

## The Pipeline

```text
┌─────────────────────────────────────────────────────────────────┐
│ git push → GitHub Actions → SafeDB-CI │
│ │
│ Phase 1 ORDERING Sequence gaps, duplicates, naming │
│ Phase 2 SAFETY Regex scan for destructive SQL │
│ Phase 3 EXECUTION Apply migrations to ephemeral DB │
│ Phase 4 INTROSPECTION Read information_schema catalog │
│ Phase 5 VALIDATION Structural integrity checks │
│ Phase 6 RESULT exit 0 ✅ or exit 1 ❌ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### Using as a GitHub Action

```yaml
# .github/workflows/validate-migrations.yml
name: Validate Migrations

on: [push, pull_request]

jobs:
validate:
runs-on: ubuntu-latest

services:
postgres:
image: postgres:15
env:
POSTGRES_USER: safedb
POSTGRES_PASSWORD: safedbpass
POSTGRES_DB: safedb_test
options: >-
--health-cmd pg_isready
--health-interval 10s
--health-timeout 5s
--health-retries 5

steps:
- uses: actions/checkout@v4

- uses: arju-z/SafeDB-CI@v1
with:
db_type: postgres
migrations_path: ./migrations
strict_mode: "true"
postgres_user: safedb
postgres_password: safedbpass
postgres_db: safedb_test
```

### Running Locally

```bash
# Install
pip install --editable .

# PostgreSQL
safedb validate \
--db-type postgres \
--migrations-path ./migrations \
--database-url "postgresql://user:pass@127.0.0.1:5432/mydb"

# MySQL
safedb validate \
--db-type mysql \
--migrations-path ./migrations \
--mysql-host 127.0.0.1 \
--mysql-user myuser \
--mysql-password mypass \
--mysql-database mydb

# CI mode — reads credentials from environment variables
export POSTGRES_USER=myuser
export POSTGRES_PASSWORD=mypass
export POSTGRES_DB=mydb

safedb validate --db-type postgres --ci --migrations-path ./migrations
```

---

## Action Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `db_type` | ✅ | — | `postgres` or `mysql` |
| `migrations_path` | ✅ | `./migrations` | Path to SQL migration files |
| `strict_mode` | ❌ | `false` | Treat MEDIUM anomalies as hard failures |
| `postgres_user` | If Postgres | — | Must match service container `POSTGRES_USER` |
| `postgres_password` | If Postgres | — | Use `${{ secrets.DB_PASSWORD }}` |
| `postgres_db` | If Postgres | — | Target database name |
| `mysql_user` | If MySQL | — | Must match service container `MYSQL_USER` |
| `mysql_password` | If MySQL | — | Use `${{ secrets.DB_PASSWORD }}` |
| `mysql_database` | If MySQL | — | Target database name |

---

## Migration Naming Convention

Files must follow: `NNN_description.sql`

```
migrations/
├── 001_create_users.sql
├── 002_create_roles.sql
├── 003_create_products.sql
└── 004_create_orders.sql
```

Rules enforced:

- Version numbers start at `001` and increment by exactly `1`
- No gaps — `001, 002, 004` fails on `004`
- No duplicate version numbers
- Any `.sql` file not matching the pattern is a hard error

---

## Safety Rules

SafeDB-CI scans SQL text before execution. No SQL parser required — it detects *intent*.

### HIGH Severity — Always blocks (exit 1)

| Pattern | Risk |
|---|---|
| `DROP TABLE` | Irrecoverable data loss |
| `DROP COLUMN` | Permanent column and data removal |
| `TRUNCATE` | Deletes all rows, no transaction log |
| `ALTER TABLE … DROP` | Drops column without `COLUMN` keyword |
| `DELETE FROM <t>` without `WHERE` | Full-table wipe |

    ### MEDIUM Severity — Warning by default, blocks in strict mode

    | Pattern | Risk |
    |---|---|
    | `CASCADE` on FK definition | Conditional child-row deletion — confirm blast radius |
    | `ALTER COLUMN TYPE` | May silently truncate data on cast |
    | `SET NOT NULL` | Fails in prod if NULLs already exist in the column |

    ---

    ## Schema Structural Validation

    After migrations execute, SafeDB-CI reads `information_schema` and validates the resulting schema:

    | Check | Severity |
    |---|---|
    | FK references a table that doesn't exist | HIGH |
    | FK references a column that doesn't exist | HIGH |
    | FK references a non-unique, non-PK column | HIGH |
    | Duplicate FK constraints (same column mapping) | MEDIUM |
    | Table has no PRIMARY KEY | MEDIUM |

    ---

    ## Strict Mode

    ```
    strict_mode: false (default)
    HIGH violations → ❌ fail (exit 1)
    MEDIUM warnings → ⚠ print, continue (exit 0)

    strict_mode: true
    HIGH violations → ❌ fail (exit 1)
    MEDIUM warnings → ❌ fail (exit 1)
    ```

    **Recommended policy:** `strict_mode: false` on feature branches, `strict_mode: true` on `main`.

    ---

    ## Database Notes

    ### PostgreSQL ✅

    DDL statements (`CREATE TABLE`, `ALTER TABLE`) are fully transactional. A failed migration is completely rolled back
    — the database is left exactly as it was before.

    ### MySQL ⚠️

    MySQL issues an implicit `COMMIT` before and after every DDL statement. **A failed migration cannot be fully rolled
    back.** Any DDL that executed before the failure is permanently committed.

    **Mitigation:** Write exactly one DDL statement per migration file. Always use `ENGINE=InnoDB`.

    ---

    ## Environment Variables (CI Mode)

    When `--ci` is active, credentials are read from environment variables instead of CLI arguments.

    | Variable | Engine |
    |---|---|
    | `POSTGRES_USER` | PostgreSQL |
    | `POSTGRES_PASSWORD` | PostgreSQL |
    | `POSTGRES_DB` | PostgreSQL |
    | `MYSQL_USER` | MySQL |
    | `MYSQL_PASSWORD` | MySQL |
    | `MYSQL_DATABASE` | MySQL |

    Host defaults to `127.0.0.1`. Port defaults to `5432` (Postgres) or `3306` (MySQL).

    ---

    ## Exit Codes

    | Code | Meaning |
    |---|---|
    | `0` | All phases passed. Safe to deploy. |
    | `1` | One or more phases failed. Do NOT deploy. |

    ---

    ## Local Development

    ```bash
    # Clone the repo
    git clone https://github.com/arju-z/SafeDB-CI.git
    cd SafeDB-CI

    # Set up Python environment
    python3 -m venv venv
    source venv/bin/activate
    pip install --editable ".[dev]"

    # Start local databases
    docker compose up -d

    # Run validation
    safedb validate \
    --db-type postgres \
    --migrations-path ./migrations \
    --database-url "postgresql://safedb:safedbpass@127.0.0.1:5432/safedb_test"
    ```

    ---

    ## Project Structure

    ```
    SafeDB-CI/
    ├── action.yml # GitHub Action entrypoint (composite)
    ├── pyproject.toml # Python package definition
    ├── engine/
    │ ├── cli.py # CLI: argument parsing, orchestration
    │ ├── versioning.py # Phase 1: migration ordering validation
    │ ├── safety.py # Phase 2: destructive SQL detection
    │ ├── executor.py # Phase 3: migration execution
    │ ├── schema.py # Phases 4–5: introspection + validation
    │ ├── errors.py # Domain exception hierarchy
    │ ├── models.py # Migration dataclass
    │ └── adapters/
    │ ├── postgres.py # PostgreSQL adapter
    │ └── mysql.py # MySQL adapter
    ├── migrations/ # Example migrations
    └── .github/workflows/
    └── migrations.yml # CI workflow using this action
    ```

    ---

    ## Known Limitations

    - **No production schema diff** — validates internal self-consistency only, not against a baseline
    - **No data-level validation** — the CI database is always empty; runtime data constraints cannot be tested
    - **No detection of missing constraints** — can't flag a forgotten FK or index
    - **PostgreSQL: `public` schema only** — multi-schema databases not supported in v1
    - **Pattern-based safety** — regex, not a SQL AST; complex nested statements may not be caught

    ---

    ## Contributing

    1. Fork the repository
    2. Create a feature branch: `git checkout -b feature/my-change`
    3. Keep the engine layer separation clean — adapters must not leak into CLI, CLI must not contain business logic
    4. Add comments explaining *why*, not just *what*
    5. Submit a pull request against `main`

    All pull requests are validated by SafeDB-CI itself.

    ---

    ## License

    MIT © SafeDB-CI Contributors