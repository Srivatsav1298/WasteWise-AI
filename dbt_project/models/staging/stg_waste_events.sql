-- Grain: one row per waste event (waste_id). Reason is the contract-normalized enum.
select
    waste_id,
    location_id,
    cast(waste_date as date) as waste_date,
    ingredient_id,
    cast(quantity as double) as waste_quantity,
    reason as waste_reason,
    cast(_ingested_at as timestamp) as ingested_at
from {{ source('silver', 'waste_events') }}
