-- Mart: mart_builder_scorecard  (Module 1)
-- Final analytical table powering the Builder Reliability Scorecard
-- Queried directly by Power BI Page 2

with projects as (
    select * from {{ ref('stg_projects') }}
),

complaints as (
    select * from {{ ref('stg_complaints') }}
),

-- Step 1: calculate delay days per project
project_delays as (
    select
        project_id,
        project_name,
        trim(lower(builder_name_raw))       as builder_key,
        builder_name_raw                    as builder_name,
        district,
        locality,
        approved_units,
        registration_date,
        expected_completion_date,
        actual_completion_date,
        project_status,

        -- delay in days; NULL = project still active (not yet delivered)
        case
            when actual_completion_date is not null
            then actual_completion_date - expected_completion_date
            else null
        end                                 as delay_days,

        -- flag: delivered on time
        case
            when actual_completion_date <= expected_completion_date then true
            else false
        end                                 as delivered_on_time
    from projects
),

-- Step 2: complaint rate per builder
complaint_counts as (
    select
        builder_key,
        count(*)                            as complaint_count
    from complaints
    group by builder_key
),

-- Step 3: join and compute builder-level aggregates
builder_scores as (
    select
        pd.builder_key,
        pd.builder_name,
        pd.district,
        count(pd.project_id)                as total_projects,
        sum(pd.approved_units)              as total_units,
        round(avg(pd.delay_days)::numeric, 1)   as avg_delay_days,
        round(avg(pd.delay_days)::numeric / 30, 1) as avg_delay_months,
        count(case when pd.delivered_on_time then 1 end) as on_time_count,
        round(
            count(case when pd.delivered_on_time then 1 end)::numeric /
            nullif(count(pd.project_id), 0) * 100, 1
        )                                   as on_time_pct,
        coalesce(cc.complaint_count, 0)     as total_complaints,
        -- complaints per 100 approved units
        round(
            coalesce(cc.complaint_count, 0)::numeric /
            nullif(sum(pd.approved_units), 0) * 100, 2
        )                                   as complaints_per_100_units
    from project_delays pd
    left join complaint_counts cc on pd.builder_key = cc.builder_key
    group by pd.builder_key, pd.builder_name, pd.district, cc.complaint_count
    having count(pd.project_id) >= 3       -- min 3 projects for statistical relevance
),

-- Step 4: NTILE quartile ranking (1 = best, 4 = worst)
ranked as (
    select
        *,
        ntile(4) over (order by avg_delay_days asc nulls last)  as delay_quartile,
        ntile(4) over (order by on_time_pct desc)               as reliability_quartile,
        ntile(4) over (order by complaints_per_100_units asc)   as complaint_quartile
    from builder_scores
)

select
    *,
    -- composite risk tier: average of the three quartile rankings
    round((delay_quartile + complaint_quartile)::numeric / 2, 0)::int as risk_tier
from ranked
order by avg_delay_days desc nulls last
