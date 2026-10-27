-- What to buy, where, and how much waste that purchase is carrying.
-- Grain: location_id + ingredient_id.
-- Recommendation logic is deliberately simple and explainable: cover days of
-- average demand, minus stock on hand. It is a planning aid, not a forecast.
with demand as (
    select
        location_id,
        ingredient_id,
        sum(ingredient_demand_qty) as demand_qty_30d,
        count(distinct sale_date) as days_with_demand
    from {{ ref('int_sales_ingredient_demand') }}
    group by 1, 2
),
waste as (
    select
        location_id,
        ingredient_id,
        sum(waste_quantity) as waste_qty_30d,
        round(sum(estimated_cost), 2) as waste_cost_30d,
        count(*) as waste_event_count
    from {{ ref('int_waste_with_context') }}
    group by 1, 2
),
stock as (
    select location_id, ingredient_id, event_date as snapshot_date, quantity_on_hand
    from {{ ref('fct_inventory_snapshot') }}
    qualify row_number() over (partition by location_id, ingredient_id order by event_date desc) = 1
),
last_event as (
    select location_id, ingredient_id, max(waste_date) as last_waste_date
    from {{ ref('int_waste_with_context') }}
    group by 1, 2
)
select
    d.location_id,
    l.location_name,
    d.ingredient_id,
    i.ingredient_name,
    i.ingredient_category,
    i.ingredient_unit,
    i.unit_cost,
    s.snapshot_date as stock_as_of,
    s.quantity_on_hand as stock_on_hand,
    round(d.demand_qty_30d / nullif(d.days_with_demand, 0), 3) as avg_daily_demand,
    round(d.demand_qty_30d, 3) as demand_qty_30d,
    w.waste_qty_30d,
    w.waste_cost_30d,
    w.waste_event_count,
    e.last_waste_date,
    round(w.waste_qty_30d / nullif(d.demand_qty_30d, 0), 6) as waste_rate_30d,
    round(
        greatest(0, (d.demand_qty_30d / nullif(d.days_with_demand, 0)) * {{ var('target_cover_days') }} - s.quantity_on_hand),
        2
    ) as recommended_order_qty,
    round(
        greatest(0, (d.demand_qty_30d / nullif(d.days_with_demand, 0)) * {{ var('target_cover_days') }} - s.quantity_on_hand) * i.unit_cost,
        2
    ) as recommended_order_cost,
    case
        when w.waste_qty_30d / nullif(d.demand_qty_30d, 0) >= 0.08 then 'reduce_order'
        when w.waste_qty_30d / nullif(d.demand_qty_30d, 0) >= 0.03 then 'watch'
        else 'normal'
    end as purchase_action
from demand d
join {{ ref('dim_location') }} l on l.location_id = d.location_id
join {{ ref('dim_ingredient') }} i on i.ingredient_id = d.ingredient_id
left join stock s on s.location_id = d.location_id and s.ingredient_id = d.ingredient_id
left join waste w on w.location_id = d.location_id and w.ingredient_id = d.ingredient_id
left join last_event e on e.location_id = d.location_id and e.ingredient_id = d.ingredient_id
