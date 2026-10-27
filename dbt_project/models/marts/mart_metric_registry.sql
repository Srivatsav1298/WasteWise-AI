-- Metric registry: the contract between the warehouse and every consumer.
--
-- One row per published metric. It states what the metric means, where the
-- number comes from, whether it is measured, derived or estimated, and the
-- conditions under which it may be shown. The dashboard reads this table and
-- refuses to display a metric whose trust state is not allowed.
with metrics as (
    select * from (
        values
            ('waste_cost_at_risk', 'Waste cost at risk', 'marts', 'mart_food_loss_summary',
             'Value of avoidable recorded waste priced at purchase-unit cost.',
             'sum(estimated_cost where avoidability_flag = 1)', null, 'NOK', 'derived',
             array['measured', 'partial'], 'ops analytics',
             'Cost uses purchase-unit cost, not a landed or net-of-discount cost.', true, true),
            ('avoidable_cost_share', 'Avoidable cost share', 'marts', 'mart_food_loss_summary',
             'Share of waste cost whose reason is classified avoidable or potentially avoidable.',
             'sum(estimated_cost where avoidability_flag = 1)', 'sum(estimated_cost)', 'percent', 'derived',
             array['measured', 'partial'], 'ops analytics',
             'Avoidability is a policy classification maintained in dim_waste_reason.', true, true),
            ('waste_rate_per_demand', 'Waste rate per demand', 'marts', 'mart_food_loss_summary',
             'Total waste quantity divided by the total demand of the same ingredients, '
             'on the same days and locations. A ratio of totals, not an average of daily ratios.',
             'sum(waste_quantity)', 'sum(ingredient_demand_qty)', 'ratio', 'derived',
             array['measured'], 'ops analytics',
             'The denominator covers the ingredients that were wasted, not the whole menu. '
             'Published only where a demand denominator exists.', true, true),
            ('waste_quantity', 'Waste quantity', 'marts', 'mart_food_loss_summary',
             'Quantity of food recorded as wasted, in the unit of the ingredient.',
             'sum(waste_quantity)', null, 'kg_or_unit', 'measured',
             array['measured', 'partial', 'unverified'], 'ops',
             'Sum of source-recorded quantity from fct_waste_events. No estimation is applied.', true, true),
            ('units_sold', 'Units sold', 'facts', 'fct_sales',
             'Units of a product sold, as reported by the point-of-sale system.',
             'sum(units_sold)', null, 'units', 'measured',
             array['measured'], 'ops', 'Point-of-sale system of record.', true, false),
            ('demand_lift_pct', 'Demand lift around events', 'marts', 'mart_demand_events',
             'Change in average daily units sold in the 7 days around an event versus the 17 days before it.',
             'window_units_sold / 7', 'baseline_daily_units', 'percent', 'derived',
             array['measured'], 'demand planning',
             'Measured lift only. Forward-looking events carry no lift value. '
             'The demand index counts units sold, so it compares like with like across mixed products.', true, true),
            ('expected_attendance', 'Expected attendance', 'facts', 'fct_demand_events',
             'Organiser estimate of event attendance.',
             'expected_attendance', null, 'people', 'estimated',
             array['measured', 'partial', 'unverified'], 'demand planning',
             'An estimate, not a measurement. Confidence is carried per event.', true, true),
            ('recommended_order_qty', 'Recommended order quantity', 'marts', 'mart_purchase_plan',
             'Cover days of average demand minus stock on hand.',
             'avg_daily_demand * cover_days', 'stock_on_hand', 'units', 'estimated',
             array['measured', 'partial'], 'purchasing',
             'Planning heuristic. Not a forecast and not an order commitment.', true, true)
    ) as t(
        metric_key, metric_name, layer, source_model, definition, numerator, denominator,
        unit, measurement_type, trust_states_allowed, owner, caveat, published, display_in_dashboard
    )
)
select
    metric_key,
    metric_name,
    layer,
    source_model,
    definition,
    numerator,
    denominator,
    unit,
    measurement_type,
    trust_states_allowed,
    owner,
    caveat,
    published,
    display_in_dashboard
from metrics
