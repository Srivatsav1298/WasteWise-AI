-- Converts point-of-sale units into ingredient demand.
-- Grain: sale_date + location_id + ingredient_id.
-- This is the denominator for waste rates. Aggregating before joining to waste
-- is what keeps the fact from fanning out.
select
    s.sale_date,
    s.location_id,
    p.ingredient_id,
    sum(s.units_sold) as units_sold_total,
    round(sum(s.units_sold * p.qty_per_unit), 4) as ingredient_demand_qty,
    count(distinct s.product_id) as product_count
from {{ ref('stg_sales') }} s
join {{ ref('stg_products') }} p on p.product_id = s.product_id
group by 1, 2, 3
