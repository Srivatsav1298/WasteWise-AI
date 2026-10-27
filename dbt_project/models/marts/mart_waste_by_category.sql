-- Grain: ingredient_category.
select
    ingredient_category as category,
    sum(waste_quantity) as total_qty,
    round(sum(estimated_cost), 2) as total_cost,
    count(*) as events,
    count(distinct ingredient_id) as ingredient_count,
    round(avg(has_demand_denominator), 4) as demand_coverage
from {{ ref('int_waste_with_context') }}
group by 1
