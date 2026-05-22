# Data Dictionary — HydRERA Analytics

Complete reference for every table and column in the project.

---

## Raw Tables (written by `ingest.py`)

### `raw_rera_projects`
Source: RERA Telangana portal — project registry

| Column | Type | Description |
|--------|------|-------------|
| `project_id` | TEXT (PK) | RERA registration number e.g. `P/TG/HYD/0001/2017` |
| `project_name` | TEXT | Name of the residential project |
| `builder_name` | TEXT | Promoter / developer name as registered |
| `district` | TEXT | District (Hyderabad, Ranga Reddy, Medchal etc.) |
| `locality` | TEXT | Mandal / micro-market area |
| `project_type` | TEXT | `residential`, `commercial`, `mixed` |
| `approved_units` | INTEGER | Total approved dwelling units |
| `registration_date` | DATE | Date RERA registration was granted |
| `expected_completion_date` | DATE | Promised delivery date per registration |
| `actual_completion_date` | DATE | NULL if project still active |
| `project_status` | TEXT | `completed`, `ongoing`, `new_launch`, `lapsed` |
| `_loaded_at` | TIMESTAMP | Pipeline load timestamp |

---

### `raw_rera_complaints`
Source: RERA Telangana portal — complaint registry

| Column | Type | Description |
|--------|------|-------------|
| `complaint_id` | TEXT (PK) | RERA complaint case number |
| `builder_name` | TEXT | Respondent builder name |
| `project_name` | TEXT | Project the complaint relates to |
| `complaint_category` | TEXT | e.g. `Delay in Possession`, `Refund`, `Defects` |
| `complaint_date` | DATE | Date complaint was filed |
| `resolution_status` | TEXT | `resolved`, `pending`, `dismissed` |
| `days_to_resolution` | INTEGER | Days from filing to resolution. NULL if pending |
| `_loaded_at` | TIMESTAMP | Pipeline load timestamp |

---

### `raw_property_registrations`
Source: Telangana Registration & Stamps Dept / data.opencity.in

| Column | Type | Description |
|--------|------|-------------|
| `transaction_id` | TEXT (PK) | Sale deed registration document number |
| `locality` | TEXT | Sub-registrar office / locality |
| `district` | TEXT | District name |
| `registration_date` | DATE | Date of sale deed registration |
| `area_sqft` | NUMERIC | Property built-up area in square feet |
| `total_price_inr` | NUMERIC | Total consideration amount in INR |
| `price_per_sqft` | NUMERIC | Derived: `total_price_inr / area_sqft` |
| `property_type` | TEXT | `Flat`, `Villa`, `Plot`, etc. |
| `_loaded_at` | TIMESTAMP | Pipeline load timestamp |

---

## DBT Staging Views (`schema: staging`)

### `stg_projects`
Cleaned version of `raw_rera_projects`. Same columns, with:
- Dates parsed and validated
- `builder_name` trimmed and title-cased
- `project_status` normalised to 4 standard values
- Rows with null `project_id` removed

### `stg_builders`
Deduplicated builder dimension — one row per unique builder.
Adds a `builder_key` (lowercase normalised) for consistent joining.

### `stg_complaints`
Cleaned `raw_rera_complaints` with `builder_key` added.

### `stg_transactions`
Cleaned `raw_property_registrations`.
Filters out: `price_per_sqft < 500` or `> 100,000` (data errors).

---

## DBT Mart Tables (`schema: marts`)

### `mart_builder_scorecard`
One row per builder (minimum 3 projects).

| Column | Description |
|--------|-------------|
| `builder_name` | Builder display name |
| `total_projects` | Number of RERA-registered projects |
| `total_units` | Sum of all approved units |
| `avg_delay_days` | Mean delay across completed projects (negative = early) |
| `avg_delay_months` | `avg_delay_days / 30` |
| `on_time_pct` | % projects delivered on or before promised date |
| `complaints_per_100_units` | Total complaints ÷ total units × 100 |
| `delay_quartile` | 1 (best) to 4 (worst) — delay ranking |
| `reliability_quartile` | 1 (best) to 4 (worst) — on-time ranking |
| `complaint_quartile` | 1 (best) to 4 (worst) — complaint ranking |
| `risk_tier` | Composite: 1=Low Risk, 2=Moderate, 3=High Risk, 4=Very High |
| `risk_label` | Human-readable risk tier label |

---

### `mart_supply_demand`
One row per locality × quarter.

| Column | Description |
|--------|-------------|
| `locality` | Hyderabad micro-market |
| `report_quarter` | Quarter start date (e.g. `2023-10-01`) |
| `units_approved` | RERA-approved units that quarter (supply) |
| `units_sold` | Registered sale deeds that quarter (demand) |
| `rolling_4q_supply` | Cumulative supply over last 4 quarters |
| `rolling_4q_demand` | Cumulative demand over last 4 quarters |
| `absorption_rate_pct` | `rolling_4q_demand / rolling_4q_supply × 100` |
| `months_of_inventory` | Quarters to clear supply at current demand pace × 3 |
| `qoq_demand_growth_pct` | Quarter-over-quarter demand change % |
| `oversupply_flag` | TRUE if `months_of_inventory > 18` |
| `market_health` | `Undersupplied / Healthy / Watch / Oversupplied` |

---

### `mart_price_fairness`
One row per active/new-launch project.

| Column | Description |
|--------|-------------|
| `project_id` | RERA project ID |
| `market_median_psf` | Trailing 4Q median price/sqft in same locality |
| `market_p10_psf` | 10th percentile (lower market bound) |
| `market_p90_psf` | 90th percentile (upper market bound) |
| `comparable_txn_count` | Number of transactions used for benchmark |
| `launch_price_psf` | Builder's quoted launch price (populate when available) |
| `premium_over_market_pct` | `(launch - median) / median × 100` |
| `price_classification` | `overpriced / premium / fair_value / below_market` |

---

### `mart_delay_features`
One row per project — feature table for ML model.

| Column | Type | Description |
|--------|------|-------------|
| `is_delayed` | INTEGER (target) | 1=delayed, 0=on-time, NULL=active |
| `feat_approved_units` | INTEGER | Project scale |
| `feat_planned_duration_days` | INTEGER | Promised build time |
| `feat_builder_avg_delay_days` | NUMERIC | Builder's historical mean delay |
| `feat_builder_delay_rate_pct` | NUMERIC | % of builder's past projects delayed |
| `feat_builder_experience` | INTEGER | Number of builder's past projects |
| `feat_complaints_per_100_units` | NUMERIC | Builder complaint density |
| `feat_builder_risk_tier` | INTEGER | 1–4 composite risk tier |
| `feat_locality_inventory_months` | NUMERIC | Local market oversupply signal |
| `feat_locality_absorption_rate` | NUMERIC | Local market demand signal |
| `feat_oversupply_flag` | INTEGER | 1 if locality is oversupplied |
| `feat_approval_lag_days` | INTEGER | Registration-to-launch gap |
