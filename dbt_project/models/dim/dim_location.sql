-- Grain: one row per cafe location.
select
    md5(location_id) as location_key,
    location_id,
    location_name,
    city,
    case when city = 'Oslo' then 'NO-03' else 'NO-46' end as region_code
from {{ ref('stg_locations') }}
