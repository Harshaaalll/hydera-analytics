-- Mart: mart_supply_demand  (Module 2)
-- Quarterly supply pipeline vs actual demand (sale deeds) per locality
-- Powers the Market Supply/Demand page in Power BI

with projects as (
    select * from {{ ref('stg_projects') }}
),

transactions as (
    select * from {{ ref('stg_transactions') }}
),

-- Supply side: RERA-approved units entering the market per quarter
supply_by_quarter as (
    select
        locality,
        district,
        date_trunc('quarter', registration_date)    as supply_quarter,
        sum(approved_units)                         as units_approved,
        count(project_id)                           as projects_launched
    from projects
    group by locality, district, date_trunc('quarter', registration_date)
),

-- Demand side: actual registered transactions per quarter (= real sales)
demand_by_quarter as (
    select
        locality,
        registration_quarter                        as demand_quarter,
        count(transaction_id)                       as units_sold,
        round(median(price_per_sqft)::numeric, 0)   as median_price_per_sqft,
        sum(total_price_inr)                        as total_transaction_value_inr
    from transactions
    group by locality, registration_quarter
),

-- Join supply and demand on locality + quarter
combined as (
    select
        coalesce(s.locality, d.locality)            as locality,
        coalesce(s.district, 'Hyderabad')           as district,
        coalesce(s.supply_quarter, d.demand_quarter) as report_quarter,
        coalesce(s.units_approved, 0)               as units_approved,
        coalesce(s.projects_launched, 0)            as projects_launched,
        coalesce(d.units_sold, 0)                   as units_sold,
        coalesce(d.median_price_per_sqft, 0)        as median_price_per_sqft,
        coalesce(d.total_transaction_value_inr, 0)  as total_transaction_value_inr
    from supply_by_quarter s
    full outer join demand_by_quarter d
        on  s.locality       = d.locality
        and s.supply_quarter = d.demand_quarter
),

-- Rolling 4-quarter absorption rate using window functions
with_absorption as (
    select
        *,
        -- cumulative supply over rolling 4 quarters
        sum(units_approved) over (
            partition by locality
            order by report_quarter
            rows between 3 preceding and current row
        )                                           as rolling_4q_supply,

        -- cumulative demand over rolling 4 quarters
        sum(units_sold) over (
            partition by locality
            order by report_quarter
            rows between 3 preceding and current row
        )                                           as rolling_4q_demand,

        -- QoQ demand growth using LAG
        lag(units_sold, 1) over (
            partition by locality
            order by report_quarter
        )                                           as prev_q_units_sold
    from combined
)

select
    *,
    -- absorption rate: what % of supply is being absorbed by demand
    round(
        rolling_4q_demand::numeric /
        nullif(rolling_4q_supply, 0) * 100, 1
    )                                               as absorption_rate_pct,

    -- months of inventory: how many months to clear current supply at demand pace
    round(
        rolling_4q_supply::numeric /
        nullif(rolling_4q_demand / 4.0, 0), 1
    )                                               as months_of_inventory,

    -- QoQ demand growth %
    round(
        (units_sold - prev_q_units_sold)::numeric /
        nullif(prev_q_units_sold, 0) * 100, 1
    )                                               as qoq_demand_growth_pct,

    -- flag: oversupply if >18 months of inventory
    case when round(rolling_4q_supply::numeric / nullif(rolling_4q_demand / 4.0, 0), 1) > 18
         then true else false
    end                                             as oversupply_flag
from with_absorption
order by locality, report_quarter
