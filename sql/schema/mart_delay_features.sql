-- Mart: mart_delay_features  (Module 4)
-- Feature engineering table for delay prediction.
-- Each row = one active project with 11 risk signals.
-- Feeds directly into notebooks/delay_model.ipynb (logistic regression / XGBoost).

with projects as (
    select * from {{ ref('stg_projects') }}
),

builder_scorecard as (
    select * from {{ ref('mart_builder_scorecard') }}
),

supply_demand as (
    select * from {{ ref('mart_supply_demand') }}
),

-- Most recent supply/demand snapshot per locality (latest quarter)
latest_locality_snapshot as (
    select distinct on (locality)
        locality,
        months_of_inventory,
        absorption_rate_pct,
        oversupply_flag
    from supply_demand
    order by locality, report_quarter desc
),

-- Builder historical delay rate (for this builder's past projects only)
builder_history as (
    select
        trim(lower(builder_name_raw))               as builder_key,
        count(*)                                    as historical_project_count,
        round(avg(
            case when actual_completion_date is not null
                 then actual_completion_date - expected_completion_date
                 else null end
        )::numeric, 0)                              as builder_avg_delay_days,
        round(
            count(case when actual_completion_date > expected_completion_date then 1 end)::numeric /
            nullif(count(actual_completion_date), 0) * 100, 1
        )                                           as builder_historical_delay_rate_pct
    from projects
    where project_status = 'completed'
    group by trim(lower(builder_name_raw))
)

select
    -- identifiers (not features — excluded before model training)
    p.project_id,
    p.project_name,
    p.builder_name_raw                                  as builder_name,
    p.locality,
    p.district,
    p.expected_completion_date,

    -- target variable: 1 = delayed, 0 = on time (NULL = still active)
    case
        when p.actual_completion_date > p.expected_completion_date then 1
        when p.actual_completion_date <= p.expected_completion_date then 0
        else null
    end                                                 as is_delayed,

    -- ── FEATURE 1: Project size (larger = harder to deliver on time)
    p.approved_units                                    as feat_approved_units,

    -- ── FEATURE 2: Project duration planned (ambitious timelines = more risk)
    p.expected_completion_date - p.registration_date    as feat_planned_duration_days,

    -- ── FEATURE 3: Builder's historical average delay
    coalesce(bh.builder_avg_delay_days, 0)              as feat_builder_avg_delay_days,

    -- ── FEATURE 4: Builder's historical delay rate %
    coalesce(bh.builder_historical_delay_rate_pct, 50)  as feat_builder_delay_rate_pct,
    -- 50% default = uncertain (new builder with no history)

    -- ── FEATURE 5: Number of past projects this builder has (experience proxy)
    coalesce(bh.historical_project_count, 0)            as feat_builder_experience,

    -- ── FEATURE 6: Builder complaint rate per 100 units
    coalesce(bs.complaints_per_100_units, 0)            as feat_complaints_per_100_units,

    -- ── FEATURE 7: Builder risk tier (1=best … 4=worst)
    coalesce(bs.risk_tier, 2)                           as feat_builder_risk_tier,

    -- ── FEATURE 8: Locality months of inventory (oversupply = funding risk)
    coalesce(lls.months_of_inventory, 12)               as feat_locality_inventory_months,

    -- ── FEATURE 9: Locality absorption rate % (low = slow market = delivery pressure)
    coalesce(lls.absorption_rate_pct, 50)               as feat_locality_absorption_rate,

    -- ── FEATURE 10: Locality oversupply flag (binary)
    case when lls.oversupply_flag then 1 else 0 end     as feat_oversupply_flag,

    -- ── FEATURE 11: Registration-to-launch gap (long gap = delayed land/approval)
    extract(days from p.registration_date - p.registration_date)::int as feat_approval_lag_days
    -- NOTE: replace with actual approval date when available from RERA docs

from projects p
left join builder_history bh
    on trim(lower(p.builder_name_raw)) = bh.builder_key
left join builder_scorecard bs
    on trim(lower(p.builder_name_raw)) = bs.builder_key
left join latest_locality_snapshot lls
    on p.locality = lls.locality
where p.project_status in ('ongoing', 'completed', 'new_launch')
order by p.registration_date desc
