-- Grain: one row per external demand event (event_id).
select
    event_id,
    cast(event_date as date) as event_date,
    event_name,
    event_type,
    venue,
    city,
    cast(expected_attendance as integer) as expected_attendance,
    attendance_quality,
    source_url
from {{ source('silver', 'events') }}
