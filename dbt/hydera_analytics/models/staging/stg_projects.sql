{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'raw_rera_projects') }}
),

renamed as (
    select
        project_id,
        project_name,
        builder_name                        as builder_name_raw,
        trim(lower(builder_name))           as builder_key,
        district,
        locality,
        project_type,
        coalesce(approved_units, 0)         as approved_units,
        registration_date::date             as registration_date,
        expected_completion_date::date      as expected_completion_date,
        actual_completion_date::date        as actual_completion_date,
        project_status,
        _loaded_at
    from source
    where project_id is not null
      and registration_date is not null
)

select * from renamed
