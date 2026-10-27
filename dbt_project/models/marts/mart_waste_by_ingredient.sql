-- Grain: ingredient_id + location_id.
select
    ingredient_id,
    min(ingredient_name) as ingredient_name,
    min(ingredient_category) as ingredient_category,
    location_id,
    sum(waste_quantity) as waste_quantity,
    round(sum(estimated_cost), 2) as total_cost,
    count(*) as waste_event_count,
    round(avg(has_demand_denominator), 4) as demand_coverage,
    round(max(waste_rate_per_demand), 6) as waste_rate_per_demand
from {{ ref('int_waste_with_context') }}
group by 1, 4
