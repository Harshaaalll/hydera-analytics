# 📊 Power BI Dashboard Setup Guide — HydRERA Analytics

> Step-by-step instructions for connecting Power BI Desktop to the HydRERA Analytics PostgreSQL database and building the 4-page interactive dashboard.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Data Connection Setup](#data-connection-setup)
- [Page 1 — Overview Dashboard](#page-1--overview-dashboard)
- [Page 2 — Builder Reliability Scorecard](#page-2--builder-reliability-scorecard)
- [Page 3 — Market Supply vs Demand](#page-3--market-supply-vs-demand)
- [Page 4 — Price Fairness & Delay Prediction](#page-4--price-fairness--delay-prediction)
- [Color Theme](#color-theme)
- [DAX Measures Reference](#dax-measures-reference)

---

## Prerequisites

Before setting up the dashboard, ensure you have:

| Requirement | Details |
|-------------|---------|
| **Power BI Desktop** | Latest version (Windows only) — [Download](https://powerbi.microsoft.com/desktop/) |
| **PostgreSQL** | Running instance with the `hydera_rera` database |
| **dbt models built** | All mart tables must exist — run `dbt run` first |
| **Npgsql driver** | PostgreSQL ODBC/OLE DB driver may be needed — Power BI usually bundles it |

### Verify Mart Tables Exist

Run this query in PostgreSQL to confirm all 4 mart tables are populated:

```sql
SELECT 'mart_builder_scorecard' AS table_name, COUNT(*) AS row_count FROM mart_builder_scorecard
UNION ALL
SELECT 'mart_supply_demand', COUNT(*) FROM mart_supply_demand
UNION ALL
SELECT 'mart_price_fairness', COUNT(*) FROM mart_price_fairness
UNION ALL
SELECT 'mart_delay_features', COUNT(*) FROM mart_delay_features;
```

---

## Data Connection Setup

### Step 1: Open Power BI Desktop

Launch Power BI Desktop and click **Get Data** from the Home ribbon.

### Step 2: Select PostgreSQL

1. In the **Get Data** dialog, search for **PostgreSQL database**
2. Click **PostgreSQL database** → **Connect**

### Step 3: Enter Connection Details

| Field | Value |
|-------|-------|
| **Server** | `localhost:5432` (or your PostgreSQL host) |
| **Database** | `hydera_rera` |
| **Data Connectivity mode** | `Import` (recommended for performance) |

Click **OK**.

### Step 4: Authenticate

1. Select the **Database** tab (not Windows)
2. Enter your PostgreSQL credentials:
   - **User name:** Your `PG_USER` from `.env`
   - **Password:** Your `PG_PASSWORD` from `.env`
3. Click **Connect**

### Step 5: Select Tables

In the **Navigator** pane, check the following 4 tables:

- [x] `mart_builder_scorecard`
- [x] `mart_supply_demand`
- [x] `mart_price_fairness`
- [x] `mart_delay_features`

Click **Load** to import all tables.

### Step 6: Verify Data Model

Go to **Model view** (left sidebar) and verify:
- All 4 tables are loaded
- Relationships may auto-detect — if not, manually create:
  - `mart_delay_features[builder_key]` → `mart_builder_scorecard[builder_key]` (Many-to-One)
  - `mart_price_fairness[builder_key]` → `mart_builder_scorecard[builder_key]` (Many-to-One)

---

## Page 1 — Overview Dashboard

**Purpose:** High-level summary of the Hyderabad real estate market from RERA data.

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  [Total Projects]  [Total Builders]  [Total Txns]  [Avg Delay] │
├─────────────────────────────┬────────────────────────────┤
│                             │                            │
│     🗺️ Map: Projects       │   🥧 Pie: Project Status  │
│        by Locality          │      Distribution          │
│                             │                            │
├─────────────────────────────┴────────────────────────────┤
│                                                          │
│          📈 Line Chart: Projects Registered Over Time    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Visual Specifications

#### KPI Cards (Top Row)

| Card | Measure | Table |
|------|---------|-------|
| **Total Projects** | `COUNTROWS(mart_price_fairness)` | `mart_price_fairness` |
| **Total Builders** | `DISTINCTCOUNT(mart_builder_scorecard[builder_key])` | `mart_builder_scorecard` |
| **Total Transactions** | `SUM(mart_supply_demand[units_sold])` | `mart_supply_demand` |
| **Avg Delay Days** | `AVERAGE(mart_builder_scorecard[avg_delay_days])` | `mart_builder_scorecard` |

#### Map Visualization

- **Visual type:** Map or Filled Map
- **Location:** `mart_price_fairness[locality]`
- **Size:** `COUNT(mart_price_fairness[project_id])`
- **Tooltip:** Project name, builder, district, price per sqft

#### Pie Chart — Project Status Distribution

- **Visual type:** Pie Chart or Donut Chart
- **Legend:** `mart_price_fairness[project_status]`
- **Values:** `COUNT(mart_price_fairness[project_id])`
- **Colors:** Ongoing → Blue, Completed → Green, Lapsed → Orange, Revoked → Red

#### Line Chart — Projects Over Time

- **Visual type:** Line Chart
- **X-axis:** `mart_price_fairness[registration_date]` (by Month or Quarter)
- **Y-axis:** `COUNT(mart_price_fairness[project_id])`
- **Trend line:** Enable to show registration trend

---

## Page 2 — Builder Reliability Scorecard

**Purpose:** Detailed builder performance analysis with risk tiers, delay metrics, and complaint tracking.

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  [Avg Delay Months]  [On-Time %]  [Complaint Rate]      │
├─────────────────────────────┬────────────────────────────┤
│                             │                            │
│  📊 Bar: Top 10 Builders   │  📊 Stacked Bar: Risk     │
│     by Avg Delay            │     Tier Distribution      │
│                             │                            │
├─────────────────────────────┴────────────────────────────┤
│                                                          │
│  📋 Table: All Builders — Sortable by all metrics        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Visual Specifications

#### KPI Cards

| Card | DAX Measure |
|------|-------------|
| **Avg Delay Months** | `Avg Delay = AVERAGE(mart_builder_scorecard[avg_delay_months])` |
| **On-Time %** | `Avg On-Time = AVERAGE(mart_builder_scorecard[on_time_pct])` |
| **Complaint Rate** | `Avg Complaints = AVERAGE(mart_builder_scorecard[complaints_per_100_units])` |

#### Bar Chart — Top 10 Builders by Delay

- **Visual type:** Clustered Bar Chart
- **Y-axis:** `mart_builder_scorecard[builder_name]` (Top N filter = 10)
- **X-axis:** `mart_builder_scorecard[avg_delay_months]`
- **Data labels:** Enabled
- **Sort:** Descending by avg_delay_months
- **Conditional formatting:** Gradient from green (low delay) to red (high delay)

#### Stacked Bar — Risk Tier Distribution

- **Visual type:** Stacked Bar Chart
- **Y-axis:** `mart_builder_scorecard[district]`
- **X-axis:** Count of builders
- **Legend:** `mart_builder_scorecard[risk_tier]`
- **Colors:**
  - Low → `#2ECC71` (Green)
  - Medium → `#F1C40F` (Yellow)
  - High → `#E67E22` (Orange)
  - Critical → `#E74C3C` (Red)

#### Table — All Builders

| Column | Field |
|--------|-------|
| Builder Name | `builder_name` |
| District | `district` |
| Total Projects | `total_projects` |
| Total Units | `total_units` |
| Avg Delay (Months) | `avg_delay_months` |
| On-Time % | `on_time_pct` |
| Complaints / 100 Units | `complaints_per_100_units` |
| Risk Tier | `risk_tier` |

- **Conditional formatting on Risk Tier:** Background color by tier (same color scheme)
- **Sort:** Default by `risk_tier` descending (Critical first)

---

## Page 3 — Market Supply vs Demand

**Purpose:** Track market dynamics by locality and quarter to identify oversupplied or high-demand micro-markets.

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  [Slicer: Locality]    [Total Inventory Months]          │
├─────────────────────────────┬────────────────────────────┤
│                             │                            │
│  📊 Combo: Units Approved  │  📈 Line: Absorption Rate │
│     vs Units Sold           │     Over Time by Locality  │
│     by Quarter              │                            │
├─────────────────────────────┴────────────────────────────┤
│                                                          │
│  🗺️ Matrix/Heatmap: Months of Inventory                │
│     (Locality × Quarter)                                 │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Visual Specifications

#### Slicer — Locality Filter

- **Visual type:** Slicer (Dropdown or List)
- **Field:** `mart_supply_demand[locality]`
- **Selection:** Multi-select enabled
- Affects all visuals on this page

#### KPI Card

| Card | DAX Measure |
|------|-------------|
| **Total Inventory Months** | `Total Inventory Months = AVERAGE(mart_supply_demand[months_of_inventory])` |

#### Combo Chart — Supply vs Demand

- **Visual type:** Line and Clustered Column Chart
- **Shared axis:** `mart_supply_demand[report_quarter]`
- **Column values:** `SUM(mart_supply_demand[units_approved])` — supply (blue bars)
- **Line values:** `SUM(mart_supply_demand[units_sold])` — demand (orange line)
- **Secondary Y-axis:** Enable for the line if scales differ significantly

#### Line Chart — Absorption Rate

- **Visual type:** Line Chart
- **X-axis:** `mart_supply_demand[report_quarter]`
- **Y-axis:** `AVERAGE(mart_supply_demand[absorption_rate_pct])`
- **Legend:** `mart_supply_demand[locality]` (for multi-locality comparison)
- **Reference line:** Add a constant line at 100% (equilibrium point)

#### Matrix / Heatmap — Months of Inventory

- **Visual type:** Matrix
- **Rows:** `mart_supply_demand[locality]`
- **Columns:** `mart_supply_demand[report_quarter]`
- **Values:** `AVERAGE(mart_supply_demand[months_of_inventory])`
- **Conditional formatting:** Background color scale
  - Green (< 6 months) → Yellow (6-12) → Orange (12-18) → Red (> 18)
- **Note:** Values > 18 correspond to `oversupply_flag = TRUE`

---

## Page 4 — Price Fairness & Delay Prediction

**Purpose:** Identify overpriced projects and explore ML features for delay-prone projects.

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  [Overpriced Projects Count]   [Avg Premium %]           │
├─────────────────────────────┬────────────────────────────┤
│                             │                            │
│  🔵 Scatter: Launch Price  │  📊 Bar: Top Overpriced   │
│     vs Market Median        │     by Premium %           │
│     (colored by flag)       │                            │
├─────────────────────────────┴────────────────────────────┤
│                                                          │
│  📋 Table: Delay Prediction Features for High-Risk      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Visual Specifications

#### KPI Cards

| Card | DAX Measure |
|------|-------------|
| **Overpriced Projects** | `Overpriced Count = CALCULATE(COUNTROWS(mart_price_fairness), mart_price_fairness[overpriced_flag] = TRUE)` |
| **Avg Premium %** | `Avg Premium = AVERAGE(mart_price_fairness[premium_over_market_pct])` |

#### Scatter Plot — Launch Price vs Market Median

- **Visual type:** Scatter Chart
- **X-axis:** `mart_price_fairness[market_median_per_sqft]`
- **Y-axis:** `mart_price_fairness[launch_price_per_sqft]`
- **Legend:** `mart_price_fairness[overpriced_flag]`
  - `FALSE` → Blue (`#3498DB`)
  - `TRUE` → Red (`#E74C3C`)
- **Size:** `mart_price_fairness[approved_units]` (optional — larger bubbles = bigger projects)
- **Details:** `mart_price_fairness[project_name]`
- **Reference line:** Diagonal line (y = x) to show fair pricing line
- **Tooltip:** Project name, builder, locality, premium %

#### Bar Chart — Top Overpriced Projects

- **Visual type:** Clustered Bar Chart
- **Y-axis:** `mart_price_fairness[project_name]` (Top N filter = 15)
- **X-axis:** `mart_price_fairness[premium_over_market_pct]`
- **Filter:** `overpriced_flag = TRUE`
- **Sort:** Descending by premium_over_market_pct
- **Data labels:** Enabled (show percentage)
- **Color:** Gradient red

#### Table — Delay Prediction Features (High-Risk)

- **Visual type:** Table
- **Filter:** `mart_delay_features[feat_builder_risk_tier]` IN (`High`, `Critical`)

| Column | Field | Format |
|--------|-------|--------|
| Project Name | `project_name` | Text |
| Builder | `builder_name` | Text |
| Locality | `locality` | Text |
| Risk Tier | `feat_builder_risk_tier` | Conditional color |
| Is Delayed | `is_delayed` | Boolean icon |
| Approved Units | `feat_approved_units` | Integer |
| Builder Avg Delay (Days) | `feat_builder_avg_delay_days` | Decimal (1) |
| Builder Delay Rate % | `feat_builder_delay_rate_pct` | Percentage |
| Complaints / 100 Units | `feat_complaints_per_100_units` | Decimal (2) |
| Inventory Months | `feat_locality_inventory_months` | Decimal (1) |
| Absorption Rate % | `feat_locality_absorption_rate` | Percentage |
| Oversupply Flag | `feat_oversupply_flag` | Boolean icon |

---

## Color Theme

Apply a professional dark theme for a polished look. In Power BI, go to **View** → **Themes** → **Customize current theme** → **Import JSON**.

Save the following as `hydera_theme.json` and import:

```json
{
  "name": "HydRERA Analytics Dark",
  "dataColors": [
    "#3498DB",
    "#E74C3C",
    "#2ECC71",
    "#F1C40F",
    "#9B59B6",
    "#E67E22",
    "#1ABC9C",
    "#34495E",
    "#ECF0F1",
    "#95A5A6"
  ],
  "background": "#1E1E2E",
  "foreground": "#CDD6F4",
  "tableAccent": "#3498DB",
  "visualStyles": {
    "*": {
      "*": {
        "background": [
          {
            "color": "#2B2B3D",
            "transparency": 10
          }
        ],
        "border": [
          {
            "color": "#45475A",
            "weight": 1
          }
        ],
        "title": [
          {
            "color": "#CDD6F4",
            "fontSize": 12,
            "fontFamily": "Segoe UI Semibold"
          }
        ],
        "labels": [
          {
            "color": "#BAC2DE",
            "fontSize": 10
          }
        ],
        "categoryAxis": [
          {
            "color": "#BAC2DE"
          }
        ],
        "valueAxis": [
          {
            "color": "#BAC2DE"
          }
        ]
      }
    },
    "card": {
      "*": {
        "background": [
          {
            "color": "#313244",
            "transparency": 0
          }
        ]
      }
    }
  },
  "good": "#2ECC71",
  "neutral": "#F1C40F",
  "bad": "#E74C3C",
  "maximum": "#E74C3C",
  "center": "#F1C40F",
  "minimum": "#2ECC71",
  "textClasses": {
    "callout": {
      "fontSize": 28,
      "fontFace": "Segoe UI Light",
      "color": "#CDD6F4"
    },
    "title": {
      "fontSize": 14,
      "fontFace": "Segoe UI Semibold",
      "color": "#CDD6F4"
    },
    "header": {
      "fontSize": 12,
      "fontFace": "Segoe UI",
      "color": "#BAC2DE"
    },
    "label": {
      "fontSize": 10,
      "fontFace": "Segoe UI",
      "color": "#A6ADC8"
    }
  }
}
```

### Theme Color Reference

| Color | Hex | Usage |
|-------|-----|-------|
| Primary Blue | `#3498DB` | Main accent, bars, links |
| Danger Red | `#E74C3C` | Critical, overpriced, delayed |
| Success Green | `#2ECC71` | On-time, low risk, healthy |
| Warning Yellow | `#F1C40F` | Medium risk, caution |
| Orange | `#E67E22` | High risk, warning tier |
| Purple | `#9B59B6` | Secondary accent |
| Background | `#1E1E2E` | Page background |
| Card Background | `#313244` | Visual card surfaces |
| Text Primary | `#CDD6F4` | Titles, main text |
| Text Secondary | `#BAC2DE` | Labels, axis text |

---

## DAX Measures Reference

Create these measures in Power BI for consistent use across dashboard pages. Go to **Modeling** → **New Measure** for each:

### Overview Measures

```dax
Total Projects = COUNTROWS(mart_price_fairness)

Total Builders = DISTINCTCOUNT(mart_builder_scorecard[builder_key])

Total Transactions = SUM(mart_supply_demand[units_sold])

Avg Delay Days = AVERAGE(mart_builder_scorecard[avg_delay_days])
```

### Builder Scorecard Measures

```dax
Avg Delay Months = AVERAGE(mart_builder_scorecard[avg_delay_months])

Avg On-Time Pct = AVERAGE(mart_builder_scorecard[on_time_pct])

Avg Complaint Rate = AVERAGE(mart_builder_scorecard[complaints_per_100_units])

Critical Builders = 
CALCULATE(
    COUNTROWS(mart_builder_scorecard),
    mart_builder_scorecard[risk_tier] = "Critical"
)

High Risk Builders = 
CALCULATE(
    COUNTROWS(mart_builder_scorecard),
    mart_builder_scorecard[risk_tier] IN {"High", "Critical"}
)
```

### Supply vs Demand Measures

```dax
Total Inventory Months = AVERAGE(mart_supply_demand[months_of_inventory])

Avg Absorption Rate = AVERAGE(mart_supply_demand[absorption_rate_pct])

Oversupplied Localities = 
CALCULATE(
    DISTINCTCOUNT(mart_supply_demand[locality]),
    mart_supply_demand[oversupply_flag] = TRUE
)

Total Supply = SUM(mart_supply_demand[units_approved])

Total Demand = SUM(mart_supply_demand[units_sold])

Supply Demand Ratio = 
DIVIDE(
    SUM(mart_supply_demand[units_approved]),
    SUM(mart_supply_demand[units_sold]),
    0
)
```

### Price Fairness Measures

```dax
Overpriced Count = 
CALCULATE(
    COUNTROWS(mart_price_fairness),
    mart_price_fairness[overpriced_flag] = TRUE
)

Overpriced Pct = 
DIVIDE(
    CALCULATE(COUNTROWS(mart_price_fairness), mart_price_fairness[overpriced_flag] = TRUE),
    COUNTROWS(mart_price_fairness),
    0
) * 100

Avg Premium Pct = AVERAGE(mart_price_fairness[premium_over_market_pct])

Avg Launch Price = AVERAGE(mart_price_fairness[launch_price_per_sqft])

Avg Market Price = AVERAGE(mart_price_fairness[market_median_per_sqft])
```

### Delay Prediction Measures

```dax
Delayed Projects = 
CALCULATE(
    COUNTROWS(mart_delay_features),
    mart_delay_features[is_delayed] = TRUE
)

Delay Rate = 
DIVIDE(
    CALCULATE(COUNTROWS(mart_delay_features), mart_delay_features[is_delayed] = TRUE),
    COUNTROWS(mart_delay_features),
    0
) * 100

Avg Builder Experience = AVERAGE(mart_delay_features[feat_builder_experience])

Avg Planned Duration = AVERAGE(mart_delay_features[feat_planned_duration_days])
```

---

## Tips & Best Practices

1. **Refresh Schedule:** Click **Transform Data** → **Data Source Settings** to update PostgreSQL credentials. Set up a scheduled refresh if publishing to Power BI Service.

2. **Performance:** Since data is imported (not DirectQuery), click **Refresh** in the Home ribbon to pull latest data after re-running `dbt run`.

3. **Drill-through:** Add drill-through pages for individual builder or locality deep-dives by right-clicking on any visual and configuring drill-through fields.

4. **Bookmarks:** Create bookmarks for common filter combinations (e.g., "Oversupplied Markets Only", "Critical Builders") for quick navigation.

5. **Mobile Layout:** Use **View** → **Mobile Layout** to create a mobile-optimized version of each page for on-the-go analysis.

---

*Last updated: 2026-05-21*
