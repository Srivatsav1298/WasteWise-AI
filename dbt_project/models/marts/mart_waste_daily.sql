-- Waste trend series.
-- Grain: waste_date + location_id.
with daily as (
    select
        waste_date,
        location_id,
        sum(waste_quantity) as waste_quantity,
        round(sum(estimated_cost), 2) as estimated_cost,
        count(*) as waste_event_count,
        round(avg(waste_rate_per_demand), 6) as avg_waste_rate_per_demand
    from {{ ref('int_waste_with_context') }}
    group by 1, 2
)
select
    waste_date,
    location_id,
    waste_quantity,
    estimated_cost,
    waste_event_count,
    avg_waste_rate_per_demand,
    round(
        avg(waste_quantity) over (
            partition by location_id order by waste_date
            rows between 6 preceding and current row
        ), 3
    ) as rolling_7d_avg_waste_qty
from daily
