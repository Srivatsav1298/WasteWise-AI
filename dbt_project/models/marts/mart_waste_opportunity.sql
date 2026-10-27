-- Business-facing waste opportunity table.
-- Grain: waste_date + location_id + ingredient_id + waste_reason.
-- Update semantics: full rebuild from immutable facts. Safe to re-run.
select
    waste_date,
    location_id,
    ingredient_id,
    min(ingredient_name) as ingredient_name,
    min(ingredient_category) as ingredient_category,
    waste_reason,
    sum(waste_quantity) as waste_quantity,
    round(sum(estimated_cost), 2) as estimated_cost,
    max(avoidability_flag) as avoidability_flag,
    max(avoidability) as avoidability,
    max(prevention_lever) as prevention_lever,
    max(units_sold_total) as units_sold_total,
    max(ingredient_demand_qty) as ingredient_demand_qty,
    max(inventory_on_hand) as inventory_on_hand,
    round(max(waste_rate_per_demand), 6) as waste_rate_per_demand,
    round(max(waste_rate_per_inventory), 6) as waste_rate_per_inventory,
    round(avg(has_demand_denominator), 4) as demand_coverage,
    round(avg(has_inventory_denominator), 4) as inventory_coverage,
    round(avg(has_cost_reference), 4) as cost_coverage,
    count(*) as waste_event_count
from {{ ref('int_waste_with_context') }}
where waste_quantity > 0
group by waste_date, location_id, ingredient_id, waste_reason
