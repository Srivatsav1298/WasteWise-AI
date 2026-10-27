-- Demand shocks: what external events did to local demand and waste.
-- Grain: event_id + location_id (one row per event per affected cafe).
-- Forward-looking events (after the data window) keep their attendance signal
-- but carry no measured lift, so the UI cannot present a forecast as a fact.
--
-- The window aggregates are computed independently and then joined. Joining the
-- demand series and the waste series to the same event window in one step
-- would multiply them against each other and inflate both totals.
with locations as (
    select * from {{ ref('dim_location') }}
),
events as (
    select * from {{ ref('fct_demand_events') }}
),
daily_demand as (
    -- Demand index: units sold per day per location. One consistent unit, so
    -- the lift is a like-for-like comparison.
    select event_date as sale_date, location_id, sum(units_sold) as units_sold
    from {{ ref('fct_sales') }}
    group by 1, 2
),
daily_waste as (
    select waste_date, location_id, sum(waste_quantity) as waste_qty, sum(estimated_cost) as waste_cost
    from {{ ref('int_waste_with_context') }}
    group by 1, 2
),
data_window as (
    select min(sale_date) as min_date, max(sale_date) as max_date from daily_demand
),
scoped as (
    select
        e.event_id,
        e.event_date,
        e.event_name,
        e.event_type,
        e.venue,
        e.city,
        e.expected_attendance,
        e.attendance_quality,
        e.attendance_confidence,
        e.demand_signal_weight,
        e.source_url,
        l.location_id,
        l.location_name,
        d.min_date,
        d.max_date,
        case when e.event_date > d.max_date then true else false end as is_forward_looking
    from events e
    join locations l on l.city = e.city
    cross join data_window d
),
window_demand as (
    select
        s.event_id,
        s.location_id,
        sum(dd.units_sold) as window_units_sold,
        count(dd.units_sold) as window_days
    from scoped s
    left join daily_demand dd
        on dd.location_id = s.location_id
        and dd.sale_date between s.event_date - 3 and s.event_date + 3
    group by 1, 2
),
window_waste as (
    select
        s.event_id,
        s.location_id,
        sum(dw.waste_qty) as window_waste_qty,
        sum(dw.waste_cost) as window_waste_cost
    from scoped s
    left join daily_waste dw
        on dw.location_id = s.location_id
        and dw.waste_date between s.event_date - 3 and s.event_date + 3
    group by 1, 2
),
baseline as (
    select
        s.event_id,
        s.location_id,
        avg(bd.units_sold) as baseline_daily_units,
        count(bd.units_sold) as baseline_days
    from scoped s
    left join daily_demand bd
        on bd.location_id = s.location_id
        and bd.sale_date between s.event_date - 24 and s.event_date - 8
    group by 1, 2
)
select
    s.event_id,
    s.event_date,
    s.event_name,
    s.event_type,
    s.venue,
    s.city,
    s.location_id,
    s.location_name,
    s.expected_attendance,
    s.attendance_quality,
    s.attendance_confidence,
    s.demand_signal_weight,
    s.is_forward_looking,
    coalesce(wd.window_units_sold, 0) as window_units_sold,
    coalesce(wd.window_days, 0) as window_days,
    coalesce(ww.window_waste_qty, 0) as window_waste_qty,
    round(coalesce(ww.window_waste_cost, 0), 2) as window_waste_cost,
    round(b.baseline_daily_units, 3) as baseline_daily_units,
    coalesce(b.baseline_days, 0) as baseline_days,
    case when s.is_forward_looking then null
         else round((coalesce(wd.window_units_sold, 0) / 7.0) - b.baseline_daily_units, 3) end
        as demand_lift_units_per_day,
    case when s.is_forward_looking then null
         else round(((coalesce(wd.window_units_sold, 0) / 7.0) / nullif(b.baseline_daily_units, 0) - 1) * 100, 1) end
        as demand_lift_pct,
    s.source_url
from scoped s
left join window_demand wd on wd.event_id = s.event_id and wd.location_id = s.location_id
left join window_waste ww on ww.event_id = s.event_id and ww.location_id = s.location_id
left join baseline b on b.event_id = s.event_id and b.location_id = s.location_id
