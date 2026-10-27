-- Ranked prevention backlog.
-- Grain: waste_date + location_id + ingredient_id + waste_reason (same as the
-- opportunity mart; ranking adds columns, it does not change the grain).
-- Ranking rule: cost x avoidability x coverage. Rows without a demand
-- denominator are still published but are flagged, never silently ranked as
-- high confidence.
with opportunity as (
    select * from {{ ref('mart_waste_opportunity') }}
),
scored as (
    select
        *,
        case when demand_coverage >= {{ var('min_coverage_for_ranking') }} then 1 else 0 end as has_sufficient_coverage,
        round(
            estimated_cost
            * avoidability_flag
            * case when demand_coverage >= {{ var('min_coverage_for_ranking') }} then 1 else 0 end
        , 2) as opportunity_score
    from opportunity
)
select
    waste_date,
    location_id,
    ingredient_id,
    ingredient_name,
    ingredient_category,
    waste_reason,
    waste_quantity,
    estimated_cost,
    avoidability,
    avoidability_flag,
    prevention_lever,
    units_sold_total,
    ingredient_demand_qty,
    inventory_on_hand,
    waste_rate_per_demand,
    waste_rate_per_inventory,
    demand_coverage,
    inventory_coverage,
    cost_coverage,
    has_sufficient_coverage,
    opportunity_score,
    row_number() over (
        order by
            opportunity_score desc,
            estimated_cost desc,
            waste_date desc,
            ingredient_id,
            location_id,
            waste_reason
    ) as priority_rank,
    case
        when opportunity_score >= {{ var('priority_tier_high') }} then 'high'
        when opportunity_score >= {{ var('priority_tier_medium') }} then 'medium'
        else 'low'
    end as priority_tier,
    case
        when demand_coverage >= {{ var('min_coverage_for_ranking') }} and cost_coverage = 1 then 'measured'
        when demand_coverage > 0 then 'partial'
        else 'unverified'
    end as trust_state
from scored
where waste_quantity > 0
