-- Business process: external demand events near a cafe.
-- Grain: one row per event (event_id).
-- Attendance is a signal, not a measurement. Its reliability is classified so
-- downstream demand lifts are weighted by how trustworthy the signal is.
select
    e.event_id,
    e.event_date as event_date,
    d.date_key,
    e.event_name,
    e.event_type,
    e.venue,
    e.city,
    e.expected_attendance,
    e.attendance_quality,
    case lower(e.attendance_quality)
        when 'published delegates' then 'high'
        when 'organiser estimate' then 'medium'
        when 'venue capacity' then 'low'
        else 'unknown'
    end as attendance_confidence,
    case lower(e.attendance_quality)
        when 'published delegates' then 1.0
        when 'organiser estimate' then 0.7
        when 'venue capacity' then 0.4
        else 0.2
    end as demand_signal_weight,
    e.source_url
from {{ ref('stg_events') }} e
left join {{ ref('dim_date') }} d on d.date_key = e.event_date
