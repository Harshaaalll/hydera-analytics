{{ config(materialized='view') }}

with projects as (
    select * from {{ ref('stg_projects') }}
),

distinct_builders as (
    select distinct
        builder_key,
        builder_name_raw,
        district
    from projects
),

numbered as (
    select
        row_number() over (order by builder_key)    as builder_id,
        builder_key,
        builder_name_raw                            as builder_name,
        district
    from distinct_builders
)

select * from numbered
