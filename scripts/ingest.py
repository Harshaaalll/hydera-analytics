"""
ingest.py — HydRERA Analytics
Reads raw CSVs from data/raw/, cleans them, and loads into PostgreSQL.

Usage:
    python scripts/ingest.py

Requires:
    pip install pandas psycopg2-binary sqlalchemy python-dotenv
"""

import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ── DB connection ──────────────────────────────────────────────────────────────
DB_URL = (
    f"postgresql+psycopg2://{os.getenv('PG_USER')}:{os.getenv('PG_PASSWORD')}"
    f"@{os.getenv('PG_HOST')}:{os.getenv('PG_PORT')}/{os.getenv('PG_DB')}"
)
engine = create_engine(DB_URL)

RAW_DIR = "data/raw"


# ── Helpers ────────────────────────────────────────────────────────────────────
def snake(col: str) -> str:
    """Convert any column name to snake_case and strip whitespace."""
    return col.strip().lower().replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "")


def load_csv(filename: str, **read_kwargs) -> pd.DataFrame:
    path = os.path.join(RAW_DIR, filename)
    df = pd.read_csv(path, encoding="utf-8", **read_kwargs)
    df.columns = [snake(c) for c in df.columns]
    print(f"  Loaded {filename}: {len(df):,} rows, {len(df.columns)} cols")
    return df


def push(df: pd.DataFrame, table: str) -> None:
    df.to_sql(table, engine, if_exists="replace", index=False, chunksize=5000)
    print(f"  Pushed {len(df):,} rows → {table}")


# ── RERA Projects ──────────────────────────────────────────────────────────────
def ingest_projects():
    print("\n[1/3] RERA Projects")
    df = load_csv("rera_projects.csv")

    # Rename to expected column names (adjust to match actual RERA CSV headers)
    rename_map = {
        "project_registration_no": "project_id",
        "name_of_project":         "project_name",
        "promoter_name":           "builder_name",
        "mandal":                  "locality",
        "date_of_registration":    "registration_date",
        "proposed_date_of_completion": "expected_completion_date",
        "actual_date_of_completion":   "actual_completion_date",
        "total_no_of_units":       "approved_units",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Parse date columns
    for col in ["registration_date", "expected_completion_date", "actual_completion_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    # Remove rows with no project ID
    df = df.dropna(subset=["project_id"])
    df["project_id"] = df["project_id"].astype(str).str.strip()

    push(df, "raw_rera_projects")


# ── RERA Complaints ────────────────────────────────────────────────────────────
def ingest_complaints():
    print("\n[2/3] RERA Complaints")
    df = load_csv("rera_complaints.csv")

    rename_map = {
        "complaint_no":       "complaint_id",
        "respondent_name":    "builder_name",
        "complaint_category": "complaint_category",
        "filing_date":        "complaint_date",
        "disposal_status":    "resolution_status",
        "days_taken":         "days_to_resolution",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "complaint_date" in df.columns:
        df["complaint_date"] = pd.to_datetime(df["complaint_date"], errors="coerce").dt.date

    df = df.dropna(subset=["complaint_id"])
    push(df, "raw_rera_complaints")


# ── Property Registrations ─────────────────────────────────────────────────────
def ingest_transactions():
    print("\n[3/3] Property Registrations")
    df = load_csv("property_registrations.csv")

    rename_map = {
        "document_no":       "registration_doc_no",
        "village_locality":  "locality",
        "district_name":     "district",
        "registration_date": "registration_date",
        "extent_sqft":       "property_area_sqft",
        "consideration_amount": "total_consideration_inr",
        "property_nature":   "property_type",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    if "registration_date" in df.columns:
        df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce").dt.date

    # Cast numerics — handle commas in Indian number formatting
    for col in ["property_area_sqft", "total_consideration_inr"]:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("₹", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop zero-area or zero-value rows (bad records)
    df = df[
        df["property_area_sqft"].gt(0) &
        df["total_consideration_inr"].gt(0)
    ]
    push(df, "raw_property_registrations")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("HydRERA Analytics — Data Ingestion")
    print("=" * 40)

    # Verify connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("DB connection: OK")

    ingest_projects()
    ingest_complaints()
    ingest_transactions()

    print("\nIngestion complete.")
    print("Next step: cd dbt/hydera_analytics && dbt run")
