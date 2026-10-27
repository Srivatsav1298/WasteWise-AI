-- Business process: point-of-sale unit sales.
-- Grain: one row per sale line (sale_id). Unique, never aggregated.
-- Dimensions: date, location, product, ingredient.
-- Measures: units_sold, ingredient demand quantity.
select
    s.sale_id,
    s.sale_date as event_date,
    d.date_key,
    l.location_key,
    s.location_id,
    p.product_key,
    p.ingredient_key,
    s.units_sold,
    p.qty_per_unit,
    round(s.units_sold * p.qty_per_unit, 4) as demand_qty,
    s.ingested_at as ingest_time
from {{ ref('stg_sales') }} s
join {{ ref('dim_date') }} d on d.date_key = s.sale_date
join {{ ref('dim_location') }} l on l.location_id = s.location_id
join {{ ref('dim_product') }} p on p.product_id = s.product_id
