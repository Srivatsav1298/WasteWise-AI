-- Grain: one row per location, snapshot date and ingredient.
select
    cast(snapshot_date as date) as snapshot_date,
    location_id,
    ingredient_id,
    cast(quantity_on_hand as double) as quantity_on_hand,
    cast(_ingested_at as timestamp) as ingested_at
from {{ source('silver', 'inventory_snapshots') }}
