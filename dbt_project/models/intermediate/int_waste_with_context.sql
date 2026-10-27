-- Adds business context to every waste event.
-- Grain: one row per waste event (waste_id). 1:1 by construction.
-- Every join is on the FULL business key (date + location + ingredient), never
-- on a partial key. The previous version joined on date + location only and
-- multiplied each waste row by every product and every ingredient on that day.
with waste as (
    select * from {{ ref('stg_waste_events') }}
),
demand as (
    select * from {{ ref('int_sales_ingredient_demand') }}
),
inventory as (
    select * from {{ ref('stg_inventory_snapshots') }}
),
ingredients as (
    select * from {{ ref('stg_ingredients') }}
),
reasons as (
    select * from {{ ref('dim_waste_reason') }}
)
select
    w.waste_id,
    w.waste_date,
    w.location_id,
    w.ingredient_id,
    w.waste_reason,
    w.waste_quantity,
    i.ingredient_name,
    i.ingredient_category,
    i.ingredient_unit,
    i.unit_cost,
    round(w.waste_quantity * i.unit_cost, 2) as estimated_cost,
    r.avoidability,
    r.avoidability_flag,
    r.prevention_lever,
    d.units_sold_total,
    d.ingredient_demand_qty,
    inv.quantity_on_hand as inventory_on_hand,
    case
        when d.ingredient_demand_qty > 0 then round(w.waste_quantity / d.ingredient_demand_qty, 6)
    end as waste_rate_per_demand,
    case
        when inv.quantity_on_hand > 0 then round(w.waste_quantity / inv.quantity_on_hand, 6)
    end as waste_rate_per_inventory,
    case when d.ingredient_demand_qty is not null then 1 else 0 end as has_demand_denominator,
    case when inv.quantity_on_hand is not null then 1 else 0 end as has_inventory_denominator,
    case when i.unit_cost is not null then 1 else 0 end as has_cost_reference
from waste w
left join demand d
    on d.sale_date = w.waste_date
    and d.location_id = w.location_id
    and d.ingredient_id = w.ingredient_id
left join inventory inv
    on inv.snapshot_date = w.waste_date
    and inv.location_id = w.location_id
    and inv.ingredient_id = w.ingredient_id
left join ingredients i on i.ingredient_id = w.ingredient_id
left join reasons r on r.waste_reason = w.waste_reason
