-- ============================================================
-- MODULE 1 — Builder Reliability Scorecard
-- HydRERA Analytics
-- ============================================================
-- Business question:
--   Which builders in Hyderabad consistently deliver on time,
--   and which ones are chronic defaulters?
--
-- Key SQL techniques used:
--   Date arithmetic for delay calculation
--   NTILE(4) for quartile ranking
--   COALESCE for NULL handling (active projects)
--   HAVING for statistical significance threshold
--   RANK() for overall leaderboard
-- ============================================================

WITH

project_delays AS (
    SELECT
        project_id,
        LOWER(TRIM(builder_name))               AS builder_key,
        TRIM(builder_name)                      AS builder_name,
        district,
        approved_units,
        actual_completion_date,

        CASE
            WHEN actual_completion_date IS NOT NULL
            THEN actual_completion_date - expected_completion_date
            ELSE NULL
        END                                     AS delay_days,

        CASE
            WHEN actual_completion_date IS NOT NULL
             AND actual_completion_date <= expected_completion_date
            THEN 1 ELSE 0
        END                                     AS on_time_flag
    FROM raw_rera_projects
),

complaint_summary AS (
    SELECT
        LOWER(TRIM(builder_name))               AS builder_key,
        COUNT(*)                                AS total_complaints,
        ROUND(AVG(days_to_resolution), 0)       AS avg_resolution_days,
        COUNT(CASE WHEN resolution_status = 'pending' THEN 1 END)
                                                AS pending_complaints
    FROM raw_rera_complaints
    GROUP BY LOWER(TRIM(builder_name))
),

builder_stats AS (
    SELECT
        pd.builder_key,
        pd.builder_name,
        pd.district,
        COUNT(pd.project_id)                    AS total_projects,
        SUM(pd.approved_units)                  AS total_units,
        ROUND(AVG(pd.delay_days), 0)            AS avg_delay_days,
        ROUND(AVG(pd.delay_days) / 30.0, 1)    AS avg_delay_months,
        MAX(pd.delay_days)                      AS worst_delay_days,
        SUM(pd.on_time_flag)                    AS on_time_count,
        COUNT(pd.actual_completion_date)        AS completed_projects,
        ROUND(
            SUM(pd.on_time_flag)::NUMERIC /
            NULLIF(COUNT(pd.actual_completion_date), 0) * 100, 1
        )                                       AS on_time_pct,
        COALESCE(cs.total_complaints, 0)        AS total_complaints,
        ROUND(
            COALESCE(cs.total_complaints, 0)::NUMERIC /
            NULLIF(SUM(pd.approved_units), 0) * 100, 2
        )                                       AS complaints_per_100_units,
        COALESCE(cs.avg_resolution_days, 0)     AS avg_complaint_resolution_days
    FROM project_delays pd
    LEFT JOIN complaint_summary cs ON pd.builder_key = cs.builder_key
    GROUP BY pd.builder_key, pd.builder_name, pd.district,
             cs.total_complaints, cs.pending_complaints, cs.avg_resolution_days
    HAVING COUNT(pd.project_id) >= 3
),

ranked AS (
    SELECT
        *,
        NTILE(4) OVER (ORDER BY avg_delay_days ASC NULLS LAST)      AS delay_quartile,
        NTILE(4) OVER (ORDER BY on_time_pct DESC NULLS LAST)        AS reliability_quartile,
        NTILE(4) OVER (ORDER BY complaints_per_100_units ASC)       AS complaint_quartile,
        RANK()   OVER (ORDER BY avg_delay_days ASC NULLS LAST)      AS overall_rank
    FROM builder_stats
)

SELECT
    overall_rank,
    builder_name,
    district,
    total_projects,
    total_units,
    completed_projects,
    COALESCE(avg_delay_days::TEXT, 'N/A')       AS avg_delay_days,
    COALESCE(avg_delay_months::TEXT, 'N/A')     AS avg_delay_months,
    on_time_count,
    COALESCE(on_time_pct::TEXT, 'N/A')          AS on_time_pct,
    total_complaints,
    complaints_per_100_units,
    delay_quartile,
    reliability_quartile,
    complaint_quartile,
    ROUND((delay_quartile + complaint_quartile)::NUMERIC / 2, 0)::INT AS risk_tier,
    CASE
        WHEN ROUND((delay_quartile + complaint_quartile)::NUMERIC / 2, 0) = 1 THEN 'Low Risk'
        WHEN ROUND((delay_quartile + complaint_quartile)::NUMERIC / 2, 0) = 2 THEN 'Moderate'
        WHEN ROUND((delay_quartile + complaint_quartile)::NUMERIC / 2, 0) = 3 THEN 'High Risk'
        ELSE 'Very High Risk'
    END                                         AS risk_label
FROM ranked
ORDER BY avg_delay_days ASC NULLS LAST;
