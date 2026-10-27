-- Grain: one row per waste reason.
-- Business rule ownership: avoidability classification and the prevention lever
-- live in dbt, not in the dashboard, so every consumer applies the same rule.
with reasons as (
    select * from (
        values
            ('spoilage', 'avoidable', 1, 'Product spoiled before it could be used', 'Reduce order size, tighten first-expiry-first-out'),
            ('expired', 'avoidable', 1, 'Shelf life elapsed before use', 'Review shelf life assumptions and date labelling'),
            ('overproduction', 'potentially_avoidable', 1, 'More produced than sold', 'Size production to forecast demand, not to traffic'),
            ('trim', 'other', 0, 'Preparation trim and peeling', 'Track trim rate as a yield KPI, not as waste'),
            ('damaged', 'other', 0, 'Handling or storage damage', 'Review handling and storage procedure'),
            ('other', 'other', 0, 'Unclassified waste', 'Investigate and re-classify at source')
    ) as t(waste_reason, avoidability, avoidability_flag, definition, prevention_lever)
)
select
    md5(waste_reason) as reason_key,
    waste_reason,
    avoidability,
    avoidability_flag,
    definition,
    prevention_lever
from reasons
