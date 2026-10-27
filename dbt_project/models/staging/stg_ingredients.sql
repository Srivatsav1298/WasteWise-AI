-- Grain: one row per ingredient.
select
    ingredient_id,
    ingredient_name,
    category as ingredient_category,
    unit as ingredient_unit,
    cast(pack_size as double) as pack_size,
    cast(unit_cost as double) as unit_cost
from {{ source('silver', 'ingredients') }}
