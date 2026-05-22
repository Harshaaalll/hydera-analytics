{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'raw_property_registrations') }}
),

renamed as (
    select
        -- Use registration_doc_no as the unique ID (matches schema.yml source definition)
        coalesce(transaction_id, registration_doc_no)   as transaction_id,
        locality,
        district,
        registration_date::date                         as registration_date,
        date_trunc('quarter', registration_date::date)  as registration_quarter,
        area_sqft::numeric                              as area_sqft,
        total_price_inr::numeric                        as total_price_inr,
        price_per_sqft::numeric                         as price_per_sqft,
        property_type,
        _loaded_at
    from source
    where price_per_sqft is not null
      and price_per_sqft between 500 and 100000
)

select * from renamed
