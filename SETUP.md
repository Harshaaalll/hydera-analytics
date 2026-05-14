# Setup guide

End-to-end instructions to reproduce the HydRERA Analytics project
from scratch on your local machine.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | python.org |
| PostgreSQL | 16+ | postgresql.org |
| DBT Core | 1.8+ | `pip install dbt-postgres` |
| Power BI Desktop | latest | microsoft.com/powerbi (Windows only) |
| Git | any | git-scm.com |

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/hydera-analytics.git
cd hydera-analytics
```

## Step 2 — Python environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Step 3 — Environment variables

```bash
cp .env.example .env
# Edit .env and fill in your PostgreSQL credentials
```

## Step 4 — Create the PostgreSQL database

```bash
createdb hydera_rera
# Verify:
psql -d hydera_rera -c "SELECT version();"
```

## Step 5 — DBT profile

Create `~/.dbt/profiles.yml` (your home directory, NOT inside the repo):

```yaml
hydera_analytics:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      user: postgres
      password: YOUR_PASSWORD
      dbname: hydera_rera
      schema: marts
      threads: 4
```

See `dbt/hydera_analytics/profiles.yml.example` for a template.

## Step 6 — Data ingestion

### Option A: Use the sample data (quickest)
```bash
python scripts/ingest.py --sample
```
This loads the 100-row sample CSVs from `data/sample/`.

### Option B: Scrape the full dataset
1. Download RERA project & complaint CSVs from https://rera.telangana.gov.in
2. Download property registration CSV from https://data.opencity.in
3. Save all files to `data/raw/`
4. Run: `python scripts/ingest.py`

## Step 7 — Run DBT models

```bash
cd dbt/hydera_analytics
dbt deps            # install dbt_utils package
dbt run             # build all staging + mart tables
dbt test            # run data quality tests
```

Expected output: 8 models created (4 staging views + 4 mart tables).

## Step 8 — Open the Power BI dashboard

1. Open `dashboard/hydera_rera.pbix` in Power BI Desktop
2. Go to Transform Data → Data source settings
3. Update the PostgreSQL server to `localhost` and database to `hydera_rera`
4. Enter your credentials and click OK
5. Click Refresh — all 4 pages will populate

---

## Troubleshooting

**`dbt run` fails with connection error**
→ Check `~/.dbt/profiles.yml` credentials match your `.env`

**`ingest.py` CSV column errors**
→ RERA portal occasionally changes column names. Check `scripts/ingest.py`
rename_map and update to match your downloaded CSV headers.

**Power BI shows no data**
→ Confirm `dbt run` completed successfully and the `marts` schema
exists in your `hydera_rera` database.
