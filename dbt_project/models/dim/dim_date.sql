-- Conformed calendar dimension. date_key is the DATE itself (no surrogate key),
-- which keeps joins between facts and the calendar trivial and auditable.
-- Grain: one row per calendar date present in any source.
with all_dates as (
    select sale_date as event_date from {{ ref('stg_sales') }}
    union all select snapshot_date from {{ ref('stg_inventory_snapshots') }}
    union all select waste_date from {{ ref('stg_waste_events') }}
    union all select event_date from {{ ref('stg_events') }}
),
bounds as (
    select min(event_date) as min_date, max(event_date) as max_date from all_dates
),
spine as (
    select cast(gs as date) as date_key
    from bounds, generate_series(min_date, max_date, interval 1 day) as t(gs)
)
select
    date_key,
    cast(year(date_key) as integer) as year_number,
    cast(quarter(date_key) as integer) as quarter_number,
    cast(month(date_key) as integer) as month_number,
    strftime(date_key, '%B') as month_name,
    cast(week(date_key) as integer) as week_of_year,
    cast(dayofweek(date_key) as integer) as day_of_week_number,
    strftime(date_key, '%A') as day_of_week_name,
    case when dayofweek(date_key) in (0, 6) then true else false end as is_weekend,
    case when date_key = last_day(date_key) then true else false end as is_month_end,
    case when date_key = last_day(date_key) or dayofweek(date_key) = 1 then true else false end as is_business_day
from spine
