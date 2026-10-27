-- Grain: one row per cafe location.
select
    location_id,
    location_name,
    city
from {{ source('silver', 'locations') }}
