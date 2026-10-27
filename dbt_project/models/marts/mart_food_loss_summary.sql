-- Food loss summary: the warehouse's own answer to "how much value is lost".
--
-- Grain: one row per location_id, plus one 'all' row for the estate total.
--
-- The dashboard used to read these numbers from ad-hoc SQL in the export script,
-- where the waste rate was an average of per-row ratios. An average of ratios
-- is dominated by days with a tiny denominator: the same data gave 86.5% by
-- averaging and 31.7% as a ratio of totals. This model publishes the ratio of
-- totals and nothing else, so the published number and the published lineage
-- are the same thing.
--
-- Demand scope is deliberate: the denominator is the demand of the ingredients
-- that were actually wasted, on the same days, in the same location. It is not
-- the demand of the whole menu, and it is not total units sold.
with waste as (
    select
        location_id,
        sum(waste_quantity) as waste_quantity,
        sum(estimated_cost) as waste_cost,
        sum(estimated_cost) filter (where avoidability_flag = 1) as avoidable_cost,
        sum(estimated_cost) filter (where avoidability_flag = 1) / nullif(sum(estimated_cost), 0) as avoidable_cost_share,
        count(*) as waste_events,
        count(*) filter (where avoidability_flag = 1) as avoidable_events,
        count(*) filter (where has_sufficient_coverage = 1) as events_with_full_coverage
    from {{ ref('mart_waste_priority') }}
    group by 1
),
demand as (
    select
        location_id,
        sum(ingredient_demand_qty) as ingredient_demand_qty,
        count(*) filter (where has_demand_denominator = 1) as events_with_demand_denominator
    from {{ ref('int_waste_with_context') }}
    group by 1
),
located as (
    select
        w.location_id,
        l.location_name,
        l.city,
        w.waste_quantity,
        w.waste_cost,
        w.avoidable_cost,
        w.avoidable_cost_share,
        w.waste_events,
        w.avoidable_events,
        w.events_with_full_coverage,
        d.ingredient_demand_qty,
        d.events_with_demand_denominator,
        w.waste_quantity / nullif(d.ingredient_demand_qty, 0) as waste_rate_per_demand
    from waste w
    join demand d on d.location_id = w.location_id
    left join {{ ref('dim_location') }} l on l.location_id = w.location_id
),
estate as (
    select
        'all' as location_id,
        'All locations' as location_name,
        null as city,
        sum(waste_quantity) as waste_quantity,
        sum(waste_cost) as waste_cost,
        sum(avoidable_cost) as avoidable_cost,
        sum(avoidable_cost) / nullif(sum(waste_cost), 0) as avoidable_cost_share,
        cast(sum(waste_events) as bigint) as waste_events,
        cast(sum(avoidable_events) as bigint) as avoidable_events,
        cast(sum(events_with_full_coverage) as bigint) as events_with_full_coverage,
        sum(ingredient_demand_qty) as ingredient_demand_qty,
        cast(sum(events_with_demand_denominator) as bigint) as events_with_demand_denominator,
        sum(waste_quantity) / nullif(sum(ingredient_demand_qty), 0) as waste_rate_per_demand
    from located
)
select
    location_id,
    location_name,
    city,
    1 as is_total,
    round(waste_quantity, 3) as waste_quantity,
    round(ingredient_demand_qty, 3) as ingredient_demand_qty,
    round(waste_rate_per_demand, 6) as waste_rate_per_demand,
    round(waste_cost, 2) as waste_cost,
    round(avoidable_cost, 2) as avoidable_cost,
    round(avoidable_cost_share, 6) as avoidable_cost_share,
    waste_events,
    avoidable_events,
    events_with_full_coverage,
    events_with_demand_denominator
from estate
union all
select
    location_id,
    location_name,
    city,
    0 as is_total,
    round(waste_quantity, 3) as waste_quantity,
    round(ingredient_demand_qty, 3) as ingredient_demand_qty,
    round(waste_rate_per_demand, 6) as waste_rate_per_demand,
    round(waste_cost, 2) as waste_cost,
    round(avoidable_cost, 2) as avoidable_cost,
    round(avoidable_cost_share, 6) as avoidable_cost_share,
    waste_events,
    avoidable_events,
    events_with_full_coverage,
    events_with_demand_denominator
from located
