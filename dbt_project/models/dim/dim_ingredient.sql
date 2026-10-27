-- Grain: one row per ingredient.
-- unit_cost is the cost of ONE purchase unit (kg, litre or loaf). No kg
-- conversion is invented: ingredients measured in other units keep their own
-- unit so downstream cost maths never mixes units.
select
    md5(ingredient_id) as ingredient_key,
    ingredient_id,
    ingredient_name,
    ingredient_category,
    ingredient_unit,
    pack_size,
    unit_cost,
    round(unit_cost * pack_size, 2) as pack_cost,
    case ingredient_unit
        when 'kg' then 'weight'
        when 'l' then 'volume'
        else 'unit'
    end as measure_kind
from {{ ref('stg_ingredients') }}
