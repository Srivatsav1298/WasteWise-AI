-- Business process: recorded food waste.
-- Grain: one row per waste event (waste_id). Unique, never aggregated.
-- Dimensions: date, location, ingredient, waste reason.
-- Measures: waste_quantity, unit_cost, estimated_cost.
-- Reference lookups are LEFT joins so an orphaned event stays visible to the
-- trust engine instead of disappearing from the fact table.
select
    w.waste_id,
    w.waste_date as event_date,
    d.date_key,
    l.location_key,
    i.ingredient_key,
    r.reason_key,
    w.location_id,
    w.ingredient_id,
    w.waste_reason,
    w.waste_quantity,
    i.ingredient_unit,
    i.unit_cost,
    round(w.waste_quantity * i.unit_cost, 2) as estimated_cost,
    case when l.location_key is null then 0 else 1 end as has_location_reference,
    case when i.ingredient_key is null then 0 else 1 end as has_ingredient_reference,
    case when i.unit_cost is null then 0 else 1 end as has_cost_reference,
    w.ingested_at as ingest_time
from {{ ref('stg_waste_events') }} w
left join {{ ref('dim_date') }} d on d.date_key = w.waste_date
left join {{ ref('dim_location') }} l on l.location_id = w.location_id
left join {{ ref('dim_ingredient') }} i on i.ingredient_id = w.ingredient_id
left join {{ ref('dim_waste_reason') }} r on r.waste_reason = w.waste_reason
