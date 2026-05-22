-- ============================================================
-- MODULE 2 — Micro-Market Supply vs. Demand Analysis
-- HydRERA Analytics
-- ============================================================
-- Business question:
--   Which localities are oversupplied vs. healthy vs. undersupplied?
--
-- Key SQL techniques used:
--   DATE_TRUNC for quarterly bucketing
--   SUM() OVER with ROWS BETWEEN for rolling 4-quarter windows
--   LAG() for quarter-over-quarter growth rates
--   FULL OUTER JOIN to catch supply-only or demand-only quarters
--   PERCENTILE_CONT for true statistical median
-- ============================================================

WITH

supply_by_quarter AS (
    SELECT
        TRIM(locality)                              AS locality,
        district,
        DATE_TRUNC('quarter', registration_date)::DATE AS report_quarter,
        SUM(approved_units)                         AS units_approved,
        COUNT(project_id)                           AS projects_launched
    FROM raw_rera_projects
    WHERE registration_date IS NOT NULL
    GROUP BY TRIM(locality), district,
             DATE_TRUNC('quarter', registration_date)
),

demand_by_quarter AS (
    SELECT
        TRIM(locality)                              AS locality,
        DATE_TRUNC('quarter', registration_date)::DATE AS report_quarter,
        COUNT(transaction_id)                       AS units_sold,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY price_per_sqft
        )::NUMERIC, 0)                              AS median_price_psf,
        SUM(total_price_inr)                        AS total_txn_value_inr
    FROM raw_property_registrations
    WHERE registration_date IS NOT NULL
      AND price_per_sqft BETWEEN 500 AND 100000
    GROUP BY TRIM(locality),
             DATE_TRUNC('quarter', registration_date)
),

combined AS (
    SELECT
        COALESCE(s.locality, d.locality)            AS locality,
        COALESCE(s.district, 'Hyderabad')           AS district,
        COALESCE(s.report_quarter, d.report_quarter) AS report_quarter,
        COALESCE(s.units_approved, 0)               AS units_approved,
        COALESCE(s.projects_launched, 0)            AS projects_launched,
        COALESCE(d.units_sold, 0)                   AS units_sold,
        COALESCE(d.median_price_psf, 0)             AS median_price_psf,
        COALESCE(d.total_txn_value_inr, 0)          AS total_txn_value_inr
    FROM supply_by_quarter s
    FULL OUTER JOIN demand_by_quarter d
        ON s.locality = d.locality
        AND s.report_quarter = d.report_quarter
),

rolling AS (
    SELECT
        *,
        SUM(units_approved) OVER (
            PARTITION BY locality ORDER BY report_quarter
            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
        )                                           AS rolling_4q_supply,
        SUM(units_sold) OVER (
            PARTITION BY locality ORDER BY report_quarter
            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
        )                                           AS rolling_4q_demand,
        LAG(units_sold, 1) OVER (
            PARTITION BY locality ORDER BY report_quarter
        )                                           AS prev_q_demand
    FROM combined
)

SELECT
    locality,
    district,
    report_quarter,
    units_approved,
    units_sold,
    median_price_psf,
    ROUND(total_txn_value_inr / 10000000.0, 2)  AS total_txn_value_cr,
    rolling_4q_supply,
    rolling_4q_demand,
    ROUND(rolling_4q_demand::NUMERIC /
        NULLIF(rolling_4q_supply, 0) * 100, 1)  AS absorption_rate_pct,
    ROUND(rolling_4q_supply::NUMERIC /
        NULLIF(rolling_4q_demand / 4.0, 0), 1)  AS months_of_inventory,
    ROUND((units_sold - prev_q_demand)::NUMERIC /
        NULLIF(prev_q_demand, 0) * 100, 1)      AS qoq_demand_growth_pct,
    CASE
        WHEN ROUND(rolling_4q_supply::NUMERIC /
             NULLIF(rolling_4q_demand / 4.0, 0), 1) > 18
        THEN TRUE ELSE FALSE
    END                                         AS oversupply_flag,
    CASE
        WHEN ROUND(rolling_4q_supply::NUMERIC /
             NULLIF(rolling_4q_demand / 4.0, 0), 1) <= 6  THEN 'Undersupplied'
        WHEN ROUND(rolling_4q_supply::NUMERIC /
             NULLIF(rolling_4q_demand / 4.0, 0), 1) <= 12 THEN 'Healthy'
        WHEN ROUND(rolling_4q_supply::NUMERIC /
             NULLIF(rolling_4q_demand / 4.0, 0), 1) <= 18 THEN 'Watch'
        ELSE 'Oversupplied'
    END                                         AS market_health
FROM rolling
WHERE report_quarter IS NOT NULL
ORDER BY locality, report_quarter;
