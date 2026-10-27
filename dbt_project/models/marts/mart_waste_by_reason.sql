-- Grain: waste_reason.
select
    waste_reason,
    min(avoidability) as avoidability,
    min(prevention_lever) as prevention_lever,
    sum(waste_quantity) as waste_quantity,
    round(sum(estimated_cost), 2) as total_cost,
    count(*) as waste_event_count,
    count(distinct ingredient_id) as ingredient_count,
    count(distinct location_id) as location_count,
    round(avg(has_demand_denominator), 4) as demand_coverage
from {{ ref('int_waste_with_context') }}
group by 1
