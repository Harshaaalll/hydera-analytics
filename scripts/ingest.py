"""
scripts/ingest.py — HydRERA Analytics
═══════════════════════════════════════════════════════════════════════════════
Two modes:

  1. SCRAPE + LOAD (default)
     Scrapes RERA Telangana portal and Telangana property registration data,
     saves raw CSVs to data/raw/, cleans them, loads into PostgreSQL.

       python scripts/ingest.py

  2. LOAD ONLY (if you already have CSVs in data/raw/)
     Skips scraping, just cleans and loads existing CSVs.

       python scripts/ingest.py --load-only

  3. SAMPLE MODE (no scraping, loads 100-row samples from data/sample/)
     Use this to test the pipeline without downloading real data.

       python scripts/ingest.py --sample

Install dependencies first:
  pip install requests beautifulsoup4 pandas psycopg2-binary sqlalchemy
              python-dotenv tqdm lxml

RERA Telangana portal: https://rera.telangana.gov.in
Property data portal:  https://registration.telangana.gov.in/
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import time
import argparse
import logging
import re
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

try:
    from tqdm import tqdm
    TQDM = True
except ImportError:
    TQDM = False

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hydera")

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent   # project root
RAW_DIR   = ROOT / "data" / "raw"
SAMPLE_DIR= ROOT / "data" / "sample"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ── Load env ───────────────────────────────────────────────────────────────────
load_dotenv(ROOT / ".env")

DB_URL = (
    f"postgresql+psycopg2://{os.getenv('PG_USER', 'postgres')}:"
    f"{os.getenv('PG_PASSWORD', '')}@"
    f"{os.getenv('PG_HOST', 'localhost')}:"
    f"{os.getenv('PG_PORT', '5432')}/"
    f"{os.getenv('PG_DB', 'hydera_rera')}"
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — HTTP SESSION (shared, with retries + headers)
# ══════════════════════════════════════════════════════════════════════════════

def make_session() -> requests.Session:
    """Return a requests Session with browser-like headers and retry logic."""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    retry = Retry(
        total=5,
        backoff_factor=2,           # 2s, 4s, 8s, 16s, 32s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://",  HTTPAdapter(max_retries=retry))
    return session


SESSION = make_session()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — RERA TELANGANA SCRAPER
# Portal: https://rera.telangana.gov.in/projectDetails
# The portal serves paginated HTML tables. Each page = 20 rows.
# ══════════════════════════════════════════════════════════════════════════════

RERA_BASE      = "https://rera.telangana.gov.in"
RERA_LIST_URL  = f"{RERA_BASE}/projectDetails"          # project listing page
RERA_COMP_URL  = f"{RERA_BASE}/complaintsDetails"       # complaints listing

# Column names expected from the RERA project table (adjust if portal changes)
RERA_PROJECT_COLS = [
    "sl_no",
    "project_id",
    "project_name",
    "builder_name",
    "district",
    "locality",
    "project_type",
    "approved_units",
    "registration_date",
    "expected_completion_date",
    "actual_completion_date",
    "project_status",
]

RERA_COMPLAINT_COLS = [
    "sl_no",
    "complaint_id",
    "builder_name",
    "project_name",
    "complaint_category",
    "complaint_date",
    "resolution_status",
    "days_to_resolution",
]


def _parse_rera_table(html: str, expected_cols: list[str]) -> pd.DataFrame:
    """
    Parse the first <table> found in the HTML.
    Returns a DataFrame with normalised column names.
    Falls back to positional column assignment if header detection fails.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return pd.DataFrame()

    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    if not rows:
        return pd.DataFrame()

    # Detect if first row looks like a header (contains text, not digits)
    first = rows[0]
    is_header = any(re.search(r"[a-zA-Z]", c) for c in first)

    if is_header:
        df = pd.DataFrame(rows[1:], columns=first)
        df.columns = [_snake(c) for c in df.columns]
    else:
        df = pd.DataFrame(rows)
        # Assign positional column names up to what we expect
        n = min(len(expected_cols), len(df.columns))
        df.columns = list(expected_cols[:n]) + list(range(n, len(df.columns)))

    return df


def _get_total_pages(session: requests.Session, url: str, params: dict) -> int:
    """Hit page 1 to read the total record count, then compute page count."""
    try:
        r = session.get(url, params={**params, "page": 1}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Look for text like "Total Records: 6,240" or "Showing 1-20 of 6240"
        for tag in soup.find_all(string=re.compile(r"(total|records|showing)", re.I)):
            numbers = re.findall(r"[\d,]+", tag)
            counts  = [int(n.replace(",", "")) for n in numbers if int(n.replace(",", "")) > 20]
            if counts:
                total = max(counts)
                pages = (total // 20) + (1 if total % 20 else 0)
                log.info(f"  Total records: {total:,}  →  {pages} pages")
                return pages

        # If we can't detect, default to 350 pages (~7000 records)
        log.warning("  Could not detect total pages — defaulting to 350")
        return 350

    except Exception as e:
        log.warning(f"  Page count detection failed ({e}) — defaulting to 350")
        return 350


def scrape_rera_projects(max_pages: int | None = None) -> pd.DataFrame:
    """
    Scrape all registered projects from RERA Telangana portal.
    Iterates through paginated HTML tables, 20 rows per page.

    Args:
        max_pages: cap pages for testing (None = scrape everything)

    Returns:
        DataFrame with all projects
    """
    log.info("Scraping RERA Telangana — Projects")

    params = {
        "projectStatus": "all",     # registered + ongoing + completed
        "district":      "all",
        "type":          "residential",
    }

    total_pages = _get_total_pages(SESSION, RERA_LIST_URL, params)
    if max_pages:
        total_pages = min(total_pages, max_pages)
        log.info(f"  Capped at {total_pages} pages for this run")

    all_dfs = []
    page_iter = range(1, total_pages + 1)
    if TQDM:
        page_iter = tqdm(page_iter, desc="  Projects", unit="page")

    for page in page_iter:
        try:
            r = SESSION.get(
                RERA_LIST_URL,
                params={**params, "page": page},
                timeout=30,
            )
            r.raise_for_status()
            df = _parse_rera_table(r.text, RERA_PROJECT_COLS)
            if df.empty:
                log.debug(f"  Page {page}: empty table — stopping early")
                break
            all_dfs.append(df)
            time.sleep(0.8)     # be polite — 0.8s between requests

        except requests.RequestException as e:
            log.warning(f"  Page {page} failed: {e} — skipping")
            time.sleep(3)
            continue

    if not all_dfs:
        log.error("  No project data scraped. Check portal URL / network.")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    log.info(f"  Scraped {len(result):,} project rows across {len(all_dfs)} pages")
    return result


def scrape_rera_complaints(max_pages: int | None = None) -> pd.DataFrame:
    """
    Scrape complaint / grievance records from RERA Telangana portal.
    """
    log.info("Scraping RERA Telangana — Complaints")

    params = {"status": "all", "district": "all"}
    total_pages = _get_total_pages(SESSION, RERA_COMP_URL, params)
    if max_pages:
        total_pages = min(total_pages, max_pages)

    all_dfs = []
    page_iter = range(1, total_pages + 1)
    if TQDM:
        page_iter = tqdm(page_iter, desc="  Complaints", unit="page")

    for page in page_iter:
        try:
            r = SESSION.get(
                RERA_COMP_URL,
                params={**params, "page": page},
                timeout=30,
            )
            r.raise_for_status()
            df = _parse_rera_table(r.text, RERA_COMPLAINT_COLS)
            if df.empty:
                break
            all_dfs.append(df)
            time.sleep(0.8)

        except requests.RequestException as e:
            log.warning(f"  Page {page} failed: {e} — skipping")
            time.sleep(3)
            continue

    if not all_dfs:
        log.warning("  No complaint data scraped.")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    log.info(f"  Scraped {len(result):,} complaint rows")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — PROPERTY REGISTRATION DATA
# Source: Telangana Registration & Stamps Dept open data
# Direct CSV download (updated quarterly by the government)
# ══════════════════════════════════════════════════════════════════════════════

# The Telangana government publishes property registration data as open CSV
# downloads. The URL below is the Hyderabad district residential transactions.
# If the URL changes, find the latest at: https://data.opencity.in
PROP_REG_URL = (
    "https://data.opencity.in/dataset/telangana-property-registrations/"
    "resource/hyderabad-property-registrations-2019-2024.csv"
)


def download_property_registrations() -> pd.DataFrame:
    """
    Download Telangana property registration CSV from open data portal.
    Falls back to instruction message if download fails (URL may change).
    """
    log.info("Downloading property registration data")
    save_path = RAW_DIR / "property_registrations.csv"

    try:
        log.info(f"  GET {PROP_REG_URL}")
        r = SESSION.get(PROP_REG_URL, timeout=120, stream=True)
        r.raise_for_status()

        total_size = int(r.headers.get("content-length", 0))
        downloaded = 0

        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)

        size_mb = downloaded / 1_048_576
        log.info(f"  Downloaded {size_mb:.1f} MB → {save_path}")
        df = pd.read_csv(save_path, encoding="utf-8", low_memory=False)
        log.info(f"  Loaded {len(df):,} rows")
        return df

    except Exception as e:
        log.error(
            f"  Download failed: {e}\n"
            f"  Manual fallback:\n"
            f"  1. Go to https://data.opencity.in\n"
            f"  2. Search 'Telangana property registrations Hyderabad'\n"
            f"  3. Download CSV and save to: {save_path}\n"
            f"  4. Re-run with: python scripts/ingest.py --load-only"
        )
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DATA CLEANING
# ══════════════════════════════════════════════════════════════════════════════

def _snake(col: str) -> str:
    """Convert column name to snake_case."""
    col = col.strip().lower()
    col = re.sub(r"[\s\-/()]+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_")


def _parse_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Parse multiple date columns, coercing bad values to NaT."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce").dt.date
    return df


def _parse_indian_number(series: pd.Series) -> pd.Series:
    """Handle Indian number formatting: '12,34,567' or '₹ 45.5 L'."""
    s = series.astype(str)
    s = s.str.replace("₹", "", regex=False)
    s = s.str.replace(",", "", regex=False)
    s = s.str.strip()
    # Handle lakhs shorthand: "45.5 L" → 4550000
    lakh_mask = s.str.upper().str.endswith("L")
    s_lakh = s[lakh_mask].str[:-1].str.strip()
    s = s.where(~lakh_mask, other=(pd.to_numeric(s_lakh, errors="coerce") * 100_000).astype(str))
    return pd.to_numeric(s, errors="coerce")


def clean_projects(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardise RERA project data."""
    log.info("  Cleaning projects …")

    df.columns = [_snake(c) for c in df.columns]

    # Flexible column detection — RERA portal changes names occasionally
    rename_candidates = {
        "project_id": ["project_registration_no", "reg_no", "rera_no",
                       "project_registration_number", "registration_no"],
        "project_name": ["name_of_project", "project", "scheme_name"],
        "builder_name": ["promoter_name", "developer_name", "builder",
                         "applicant_name", "promoter"],
        "locality": ["mandal", "area", "location", "village", "mandal_name"],
        "district": ["district", "dist"],
        "project_type": ["type_of_project", "project_type", "category"],
        "approved_units": ["total_no_of_units", "no_of_units", "units",
                           "total_units", "number_of_units"],
        "registration_date": ["date_of_registration", "reg_date",
                              "registration_date", "approved_date"],
        "expected_completion_date": ["proposed_date_of_completion",
                                     "completion_date", "proposed_completion",
                                     "expected_completion"],
        "actual_completion_date": ["actual_date_of_completion",
                                   "actual_completion", "completion_actual"],
        "project_status": ["status", "project_status", "current_status"],
    }
    actual_cols = set(df.columns)
    for target, candidates in rename_candidates.items():
        if target not in actual_cols:
            for c in candidates:
                if c in actual_cols:
                    df = df.rename(columns={c: target})
                    break

    # Dates
    df = _parse_dates(df, [
        "registration_date",
        "expected_completion_date",
        "actual_completion_date",
    ])

    # Numeric
    if "approved_units" in df.columns:
        df["approved_units"] = pd.to_numeric(
            df["approved_units"].astype(str).str.replace(",", ""), errors="coerce"
        ).fillna(0).astype(int)

    # Strip whitespace on string cols
    for col in ["project_name", "builder_name", "locality", "district"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title()

    # Normalise project_status to consistent values
    if "project_status" in df.columns:
        status_map = {
            r"complet": "completed",
            r"ongoing|progress|active|under": "ongoing",
            r"lapse|cancel|revoke": "lapsed",
            r"new|launch|register": "new_launch",
        }
        df["project_status"] = df["project_status"].astype(str).str.lower()
        for pattern, replacement in status_map.items():
            df.loc[df["project_status"].str.contains(pattern, regex=True, na=False), "project_status"] = replacement

    # Drop rows with no project ID
    if "project_id" in df.columns:
        df = df.dropna(subset=["project_id"])
        df["project_id"] = df["project_id"].astype(str).str.strip()
        df = df[df["project_id"] != "nan"]
        df = df.drop_duplicates(subset=["project_id"])

    log.info(f"  → {len(df):,} clean project rows")
    return df


def clean_complaints(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardise RERA complaint data."""
    log.info("  Cleaning complaints …")

    df.columns = [_snake(c) for c in df.columns]

    rename_candidates = {
        "complaint_id": ["complaint_no", "case_no", "complaint_number", "id"],
        "builder_name": ["respondent_name", "opposite_party", "promoter_name", "builder"],
        "project_name": ["project_name", "project", "subject"],
        "complaint_category": ["complaint_category", "category", "nature_of_complaint"],
        "complaint_date": ["filing_date", "date_of_filing", "date", "complaint_date"],
        "resolution_status": ["disposal_status", "status", "case_status", "outcome"],
        "days_to_resolution": ["days_taken", "resolution_days", "time_taken"],
    }
    actual_cols = set(df.columns)
    for target, candidates in rename_candidates.items():
        if target not in actual_cols:
            for c in candidates:
                if c in actual_cols:
                    df = df.rename(columns={c: target})
                    break

    df = _parse_dates(df, ["complaint_date"])

    if "days_to_resolution" in df.columns:
        df["days_to_resolution"] = pd.to_numeric(
            df["days_to_resolution"], errors="coerce"
        )

    if "builder_name" in df.columns:
        df["builder_name"] = df["builder_name"].astype(str).str.strip().str.title()

    if "complaint_id" in df.columns:
        df = df.dropna(subset=["complaint_id"])
        df["complaint_id"] = df["complaint_id"].astype(str).str.strip()
        df = df.drop_duplicates(subset=["complaint_id"])

    log.info(f"  → {len(df):,} clean complaint rows")
    return df


def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardise property registration data."""
    log.info("  Cleaning transactions …")

    df.columns = [_snake(c) for c in df.columns]

    rename_candidates = {
        "transaction_id": ["document_no", "doc_no", "registration_doc_no",
                           "document_number", "reg_doc_no"],
        "locality": ["village_locality", "village", "area", "mandal",
                     "locality", "sub_registrar_office"],
        "district": ["district", "district_name", "dist"],
        "registration_date": ["registration_date", "date_of_registration",
                              "reg_date", "doc_date"],
        "area_sqft": ["extent_sqft", "property_area", "area_in_sqft",
                      "built_up_area", "extent"],
        "total_price_inr": ["consideration_amount", "market_value",
                            "consideration_value", "amount"],
        "property_type": ["property_nature", "property_type", "nature",
                          "schedule_type"],
    }
    actual_cols = set(df.columns)
    for target, candidates in rename_candidates.items():
        if target not in actual_cols:
            for c in candidates:
                if c in actual_cols:
                    df = df.rename(columns={c: target})
                    break

    df = _parse_dates(df, ["registration_date"])

    for col in ["area_sqft", "total_price_inr"]:
        if col in df.columns:
            df[col] = _parse_indian_number(df[col])

    # Derived: price per sqft — the key metric
    if "area_sqft" in df.columns and "total_price_inr" in df.columns:
        df["price_per_sqft"] = (
            df["total_price_inr"] / df["area_sqft"].replace(0, float("nan"))
        ).round(2)

    # Filter out nonsense rows
    for col in ["area_sqft", "total_price_inr"]:
        if col in df.columns:
            df = df[df[col].gt(0)]

    # Filter extreme price outliers (< ₹500/sqft or > ₹1,00,000/sqft are data errors)
    if "price_per_sqft" in df.columns:
        df = df[df["price_per_sqft"].between(500, 100_000)]

    if "locality" in df.columns:
        df["locality"] = df["locality"].astype(str).str.strip().str.title()

    if "transaction_id" in df.columns:
        df = df.dropna(subset=["transaction_id"])
        df["transaction_id"] = df["transaction_id"].astype(str).str.strip()
        df = df.drop_duplicates(subset=["transaction_id"])

    log.info(f"  → {len(df):,} clean transaction rows")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — POSTGRES LOADER
# ══════════════════════════════════════════════════════════════════════════════

def get_engine():
    engine = create_engine(DB_URL, pool_pre_ping=True)
    # Verify connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


def push_to_postgres(df: pd.DataFrame, table: str, engine) -> None:
    """
    Load DataFrame into PostgreSQL.
    Uses replace strategy so reruns are idempotent.
    Adds a row_loaded_at timestamp column automatically.
    """
    if df.empty:
        log.warning(f"  Skipping {table} — empty DataFrame")
        return

    df = df.copy()
    df["_loaded_at"] = datetime.utcnow()

    df.to_sql(
        table,
        engine,
        if_exists="replace",    # drop + recreate = idempotent reruns
        index=False,
        chunksize=5_000,
        method="multi",         # faster bulk insert
    )
    log.info(f"  ✓ {table}: {len(df):,} rows loaded")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SAMPLE DATA GENERATOR
# Creates realistic 100-row samples so the pipeline can run without scraping.
# ══════════════════════════════════════════════════════════════════════════════

def generate_samples():
    """Write 100-row sample CSVs to data/sample/ for quick testing."""
    import random
    from datetime import date, timedelta

    random.seed(42)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    builders = [
        "Prestige Group", "My Home Constructions", "Aparna Constructions",
        "Lodha Group", "Incor Infrastructure", "Aliens Group",
        "Manjeera Constructions", "Rainbow Group", "Vasavi Group",
        "NCC Urban", "Ramky Estates", "Jayabheri Group",
    ]
    localities = [
        "Gachibowli", "Kondapur", "Miyapur", "Kukatpally", "Manikonda",
        "Narsingi", "Kokapet", "Bachupally", "Kompally", "Shamshabad",
        "Uppal", "LB Nagar", "Himayatnagar", "Banjara Hills", "Jubilee Hills",
    ]
    statuses = ["completed", "ongoing", "new_launch", "lapsed"]

    # ── Projects sample ────────────────────────────────────────────────────
    projects = []
    for i in range(1, 101):
        reg_date = date(2017, 1, 1) + timedelta(days=random.randint(0, 2555))
        duration = random.randint(730, 1825)     # 2–5 years
        exp_date = reg_date + timedelta(days=duration)
        delay    = random.randint(-180, 540)      # negative = early
        act_date = exp_date + timedelta(days=delay) if random.random() > 0.3 else None
        status   = "completed" if act_date else random.choice(["ongoing", "new_launch"])
        projects.append({
            "project_id":               f"P/TG/HYD/{i:04d}/2017",
            "project_name":             f"{random.choice(builders).split()[0]} "
                                        f"{random.choice(['Heights','Residency','Enclave','Towers','Nagar'])} "
                                        f"Phase {random.randint(1,3)}",
            "builder_name":             random.choice(builders),
            "district":                 "Hyderabad",
            "locality":                 random.choice(localities),
            "project_type":             "residential",
            "approved_units":           random.randint(24, 600),
            "registration_date":        reg_date.isoformat(),
            "expected_completion_date": exp_date.isoformat(),
            "actual_completion_date":   act_date.isoformat() if act_date else "",
            "project_status":           status,
        })
    pd.DataFrame(projects).to_csv(SAMPLE_DIR / "rera_projects_sample.csv", index=False)
    log.info(f"  Sample: rera_projects_sample.csv ({len(projects)} rows)")

    # ── Complaints sample ──────────────────────────────────────────────────
    categories = [
        "Delay in Possession", "Defective Construction",
        "Refund of Advance", "Non-Registration of Sale Deed",
        "Amenities Not Provided", "Deviation from Approved Plan",
    ]
    complaints = []
    for i in range(1, 101):
        c_date = date(2018, 1, 1) + timedelta(days=random.randint(0, 2190))
        resolved = random.random() > 0.35
        complaints.append({
            "complaint_id":      f"RERA/TG/C/{i:04d}/2018",
            "builder_name":      random.choice(builders),
            "project_name":      f"Sample Project {i}",
            "complaint_category": random.choice(categories),
            "complaint_date":    c_date.isoformat(),
            "resolution_status": "resolved" if resolved else "pending",
            "days_to_resolution": random.randint(30, 360) if resolved else "",
        })
    pd.DataFrame(complaints).to_csv(SAMPLE_DIR / "rera_complaints_sample.csv", index=False)
    log.info(f"  Sample: rera_complaints_sample.csv ({len(complaints)} rows)")

    # ── Transactions sample ────────────────────────────────────────────────
    transactions = []
    for i in range(1, 101):
        reg_date  = date(2019, 1, 1) + timedelta(days=random.randint(0, 1825))
        area      = random.randint(600, 3500)
        base_psf  = {"Banjara Hills": 9000, "Jubilee Hills": 8500,
                     "Gachibowli": 6500, "Kondapur": 5800,
                     "Miyapur": 4500, "Kukatpally": 4800}.get(
            random.choice(localities), 5000
        )
        psf       = base_psf + random.randint(-500, 1500)
        price     = area * psf
        transactions.append({
            "transaction_id":   f"TG/HYD/SRO/{i:05d}/2019",
            "locality":         random.choice(localities),
            "district":         "Hyderabad",
            "registration_date": reg_date.isoformat(),
            "area_sqft":        area,
            "total_price_inr":  price,
            "price_per_sqft":   psf,
            "property_type":    random.choice(["Flat", "Villa", "Plot"]),
        })
    pd.DataFrame(transactions).to_csv(
        SAMPLE_DIR / "property_registrations_sample.csv", index=False
    )
    log.info(f"  Sample: property_registrations_sample.csv ({len(transactions)} rows)")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_scrape_and_load(sample: bool = False, load_only: bool = False,
                        max_pages: int | None = None):
    """Main pipeline: scrape → clean → load."""

    log.info("═" * 60)
    log.info("HydRERA Analytics — Ingestion Pipeline")
    log.info(f"Mode: {'SAMPLE' if sample else 'LOAD-ONLY' if load_only else 'SCRAPE + LOAD'}")
    log.info("═" * 60)

    # ── Step 1: Get / generate raw data ───────────────────────────────────
    if sample:
        log.info("\n[SETUP] Generating sample data …")
        generate_samples()
        raw_proj  = pd.read_csv(SAMPLE_DIR / "rera_projects_sample.csv")
        raw_comp  = pd.read_csv(SAMPLE_DIR / "rera_complaints_sample.csv")
        raw_trans = pd.read_csv(SAMPLE_DIR / "property_registrations_sample.csv")

    elif load_only:
        log.info("\n[SETUP] Loading existing CSVs from data/raw/ …")
        raw_proj  = _load_csv_flexible(RAW_DIR, ["rera_projects.csv", "projects.csv"])
        raw_comp  = _load_csv_flexible(RAW_DIR, ["rera_complaints.csv", "complaints.csv"])
        raw_trans = _load_csv_flexible(RAW_DIR, [
            "property_registrations.csv", "transactions.csv", "registrations.csv"
        ])

    else:
        log.info("\n[1/3] Scraping RERA Projects …")
        raw_proj = scrape_rera_projects(max_pages=max_pages)
        if not raw_proj.empty:
            raw_proj.to_csv(RAW_DIR / "rera_projects.csv", index=False)
            log.info(f"  Saved → data/raw/rera_projects.csv")

        log.info("\n[2/3] Scraping RERA Complaints …")
        raw_comp = scrape_rera_complaints(max_pages=max_pages)
        if not raw_comp.empty:
            raw_comp.to_csv(RAW_DIR / "rera_complaints.csv", index=False)
            log.info(f"  Saved → data/raw/rera_complaints.csv")

        log.info("\n[3/3] Downloading Property Registrations …")
        raw_trans = download_property_registrations()

    # ── Step 2: Clean ──────────────────────────────────────────────────────
    log.info("\n[CLEAN] Cleaning all datasets …")
    clean_proj  = clean_projects(raw_proj)   if not raw_proj.empty  else pd.DataFrame()
    clean_comp  = clean_complaints(raw_comp) if not raw_comp.empty  else pd.DataFrame()
    clean_trans = clean_transactions(raw_trans) if not raw_trans.empty else pd.DataFrame()

    # ── Step 3: Load to PostgreSQL ─────────────────────────────────────────
    log.info("\n[LOAD] Connecting to PostgreSQL …")
    try:
        engine = get_engine()
        log.info("  Connection: OK")
    except Exception as e:
        log.error(
            f"  DB connection failed: {e}\n"
            f"  Check your .env file — PG_HOST, PG_USER, PG_PASSWORD, PG_DB"
        )
        sys.exit(1)

    log.info("\n[LOAD] Pushing to PostgreSQL …")
    push_to_postgres(clean_proj,  "raw_rera_projects",         engine)
    push_to_postgres(clean_comp,  "raw_rera_complaints",       engine)
    push_to_postgres(clean_trans, "raw_property_registrations", engine)

    # ── Step 4: Summary ────────────────────────────────────────────────────
    log.info("\n" + "═" * 60)
    log.info("Ingestion complete!")
    log.info(f"  Projects loaded:     {len(clean_proj):,}")
    log.info(f"  Complaints loaded:   {len(clean_comp):,}")
    log.info(f"  Transactions loaded: {len(clean_trans):,}")
    log.info("")
    log.info("Next step:")
    log.info("  cd dbt/hydera_analytics")
    log.info("  dbt deps && dbt run && dbt test")
    log.info("═" * 60)


def _load_csv_flexible(directory: Path, filenames: list[str]) -> pd.DataFrame:
    """Try multiple possible CSV filenames, return first match."""
    for name in filenames:
        path = directory / name
        if path.exists():
            df = pd.read_csv(path, low_memory=False)
            log.info(f"  Loaded {name}: {len(df):,} rows")
            return df
    log.warning(f"  None of {filenames} found in {directory}")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HydRERA Analytics — data ingestion pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ingest.py                    # full scrape + load
  python scripts/ingest.py --sample           # sample data (no scraping)
  python scripts/ingest.py --load-only        # load existing CSVs
  python scripts/ingest.py --max-pages 5      # test scrape (first 5 pages only)
        """,
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Generate and load 100-row sample data (no scraping)",
    )
    parser.add_argument(
        "--load-only",
        action="store_true",
        help="Skip scraping — load existing CSVs from data/raw/",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Cap scraping at N pages (useful for testing)",
    )

    args = parser.parse_args()

    if args.sample and args.load_only:
        parser.error("--sample and --load-only are mutually exclusive")

    run_scrape_and_load(
        sample    = args.sample,
        load_only = args.load_only,
        max_pages = args.max_pages,
    )
