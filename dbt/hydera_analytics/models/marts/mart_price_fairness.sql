{{ config(materialized='table') }}

-- Mart: mart_price_fairness  (Module 3)
-- Launch price vs trailing 4-quarter market median by locality.
-- Key metric: premium_over_market_pct, overpriced_flag.

with projects as (
    select * from {{ ref('stg_projects') }}
),

transactions as (
    select * from {{ ref('stg_transactions') }}
),

-- Step 1: Compute median price per sqft by locality per quarter
locality_quarterly_price as (
    select
        locality,
        registration_quarter,
        percentile_cont(0.5) within group (order by price_per_sqft)  as median_price_per_sqft,
        count(*)                                                     as transaction_count,
        avg(price_per_sqft)                                          as avg_price_per_sqft,
        min(price_per_sqft)                                          as min_price_per_sqft,
        max(price_per_sqft)                                          as max_price_per_sqft
    from transactions
    group by locality, registration_quarter
),

-- Step 2: Rolling 4-quarter market median per locality
rolling_market as (
    select
        locality,
        registration_quarter,
        median_price_per_sqft   as quarter_median,
        avg(median_price_per_sqft) over (
            partition by locality
            order by registration_quarter
            rows between 3 preceding and current row
        )                       as trailing_4q_median,
        sum(transaction_count) over (
            partition by locality
            order by registration_quarter
            rows between 3 preceding and current row
        )                       as trailing_4q_txn_count
    from locality_quarterly_price
),

-- Step 3: For each RERA project, find the market median at launch time
project_launch_price as (
    select
        p.project_id,
        p.project_name,
        p.builder_name_raw                                           as builder_name,
        trim(lower(p.builder_name_raw))                              as builder_key,
        p.locality,
        p.district,
        p.registration_date,
        date_trunc('quarter', p.registration_date)                   as launch_quarter,
        p.approved_units,
        p.project_status
    from projects p
    where p.registration_date is not null
),

-- Step 4: Join projects to the rolling market median at their launch quarter
with_market as (
    select
        plp.*,
        rm.trailing_4q_median                                        as market_median_per_sqft,
        rm.trailing_4q_txn_count                                     as market_txn_count,
        rm.quarter_median                                            as launch_quarter_median
    from project_launch_price plp
    left join rolling_market rm
        on  plp.locality       = rm.locality
        and plp.launch_quarter = rm.registration_quarter
),

-- Step 5: Compute launch price proxy (using median transaction price in locality at launch quarter)
-- Since RERA data doesn't include actual launch prices, we use the quarter median as proxy
final as (
    select
        project_id,
        project_name,
        builder_name,
        builder_key,
        locality,
        district,
        registration_date,
        launch_quarter,
        approved_units,
        project_status,
        round(launch_quarter_median::numeric, 0)                     as launch_price_per_sqft,
        round(market_median_per_sqft::numeric, 0)                    as market_median_per_sqft,
        market_txn_count,

        -- premium: how much above trailing market median
        round(
            (launch_quarter_median - market_median_per_sqft)::numeric /
            nullif(market_median_per_sqft, 0) * 100, 1
        )                                                            as premium_over_market_pct,

        -- flag: overpriced if >20% above trailing 4Q median
        case
            when round(
                (launch_quarter_median - market_median_per_sqft)::numeric /
                nullif(market_median_per_sqft, 0) * 100, 1
            ) > 20 then true
            else false
        end                                                          as overpriced_flag
    from with_market
    where market_median_per_sqft is not null
)

select * from final
order by premium_over_market_pct desc nulls last
