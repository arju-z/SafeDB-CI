# SafeDB-CI Observability Stack

Receives `report.json` from GitHub Actions and displays it in Grafana via Loki.

## Architecture

```
GitHub Actions Your Server
─────────────────────────────────────────────────────
safedb validate --output json → report.json
→ curl → Loki :3100
│
Grafana :3000
(dashboard)
```

## Start the Stack

```bash
cd log
docker compose up -d
```

Open **http://localhost:3000** → login with `admin` / `safedb`

The **SafeDB-CI Migration Reports** dashboard is pre-loaded.

## Expose Loki to GitHub Actions

Loki must be reachable from GitHub Actions runners. Options:

### Option A — ngrok (quick local testing)
```bash
ngrok http 3100
# Copy the https URL e.g. https://abc123.ngrok.io
```

### Option B — VPS / cloud server
Deploy the stack on any public server. Set the IP/hostname as your `LOKI_URL` secret.

### Option C — Tailscale
Run Tailscale on the server. GitHub Actions runners can reach private networks via [Tailscale GitHub
Action](https://github.com/tailscale/github-action).

## Configure GitHub Actions

### 1. Add repository secret
```
LOKI_URL = https://your-loki-host:3100
```

### 2. Add to your workflow
```yaml
- name: Run SafeDB-CI
id: safedb
uses: arju-z/SafeDB-CI@v2
with:
db_type: postgres
migrations_path: ./migrations
strict_mode: "true"
output_format: json # ← enables report.json output
postgres_user: safedb
postgres_password: ${{ secrets.DB_PASSWORD }}
postgres_db: safedb_test

- name: Push report to Loki
if: always() # ← run even on failure
env:
LOKI_URL: ${{ secrets.LOKI_URL }}
run: |
REPORT=$(cat report.json | jq -c .)
TIMESTAMP=$(date +%s%N)
REPO="${{ github.repository }}"
BRANCH="${{ github.ref_name }}"
EXIT_CODE=$(cat report.json | jq -r '.exit_code')

curl -s -X POST "${LOKI_URL}/loki/api/v1/push" \
-H "Content-Type: application/json" \
-d "{
\"streams\": [{
\"stream\": {
\"job\": \"safedb-ci\",
\"repo\": \"${REPO}\",
\"branch\": \"${BRANCH}\",
\"exit_code\": \"${EXIT_CODE}\"
},
\"values\": [[\"${TIMESTAMP}\", ${REPORT}]]
}]
}"
```

## Query Examples in Grafana

| Goal | LogQL |
|------|-------|
| All runs | `{job="safedb-ci"}` |
| Only failures | `{job="safedb-ci", exit_code="1"}` |
| Specific repo | `{job="safedb-ci", repo="arju-z/SafeDB-CI"}` |
| Safety failures | `{job="safedb-ci"} \| json \| phases_safety_status = "fail"` |
| Count failures (7d) | `count_over_time({job="safedb-ci", exit_code="1"}[7d])` |

## Reset / Clean Data

```bash
cd log
docker compose down -v # removes volumes — wipes all stored logs
docker compose up -d
```