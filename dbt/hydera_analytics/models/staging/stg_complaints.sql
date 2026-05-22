{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'raw_rera_complaints') }}
),

renamed as (
    select
        complaint_id,
        builder_name,
        trim(lower(builder_name))                   as builder_key,
        project_name,
        complaint_category,
        complaint_date::date                        as complaint_date,
        resolution_status,
        days_to_resolution::int                     as days_to_resolution,
        _loaded_at
    from source
    where complaint_id is not null
)

select * from renamed
