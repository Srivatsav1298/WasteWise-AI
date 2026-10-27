-- Grain: one row per sale line (sale_id).
select
    sale_id,
    location_id,
    cast(sale_date as date) as sale_date,
    product_id,
    cast(units_sold as integer) as units_sold,
    cast(_ingested_at as timestamp) as ingested_at,
    _source_file,
    _run_id
from {{ source('silver', 'sales') }}
