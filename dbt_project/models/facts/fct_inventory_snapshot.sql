-- Business process: end-of-day stock on hand.
-- Grain: location + snapshot_date + ingredient. A snapshot is a state, not a
-- movement: it must not be summed across days.
select
    i.snapshot_date as event_date,
    d.date_key,
    l.location_key,
    ing.ingredient_key,
    i.location_id,
    i.ingredient_id,
    i.quantity_on_hand,
    i.ingested_at as ingest_time
from {{ ref('stg_inventory_snapshots') }} i
left join {{ ref('dim_date') }} d on d.date_key = i.snapshot_date
left join {{ ref('dim_location') }} l on l.location_id = i.location_id
left join {{ ref('dim_ingredient') }} ing on ing.ingredient_id = i.ingredient_id
