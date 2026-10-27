-- Grain: one row per product. A product consumes one ingredient, which is what
-- lets demand be converted from "units sold" to "ingredient quantity".
select
    md5(p.product_id) as product_key,
    p.product_id,
    p.product_name,
    p.product_category,
    i.ingredient_key,
    p.ingredient_id,
    p.qty_per_unit,
    p.product_unit
from {{ ref('stg_products') }} p
left join {{ ref('dim_ingredient') }} i on i.ingredient_id = p.ingredient_id
