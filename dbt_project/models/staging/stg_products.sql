-- Grain: one row per product.
select
    product_id,
    product_name,
    category as product_category,
    ingredient_id,
    cast(qty_per_unit as double) as qty_per_unit,
    unit as product_unit
from {{ source('silver', 'products') }}
