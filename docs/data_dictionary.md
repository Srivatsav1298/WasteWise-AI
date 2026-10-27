# Data dictionary

## Deliveries and cleaned sources

| Source | Entity | Grain | Key fields | Notes |
|---|---|---|---|---|
| `sales.csv` | `fct_sales` | `sale_id` | `sale_date`, `location_id`, `product_id`, `units_sold` | demand denominator for the waste rate; point of sale |
| `inventory_snapshots.csv` | `fct_inventory_snapshot` | `location_id` + `snapshot_date` + `ingredient_id` | `quantity_on_hand` | stock available before procurement |
| `waste_events.csv` | `fct_waste_events` | `waste_id` | `waste_date`, `location_id`, `ingredient_id`, `quantity`, `reason` | recorded waste; the only source of waste quantity |
| `events.csv` | `fct_demand_events` | `event_id` | `event_date`, `event_type`, `venue`, `city`, `expected_attendance`, `attendance_quality` | external demand signal; attendance is an organiser estimate |
| `ingredients.csv` | `dim_ingredient` | `ingredient_id` | `ingredient_name`, `category`, `unit`, `unit_cost` | unit is normalised to lower case (`kg`, `l`, `loaf`, `piece`, `portion`) |
| `products.csv` | `dim_product` | `product_id` | `product_name`, `category` | product master |
| `locations.csv` | `dim_location` | `location_id` | `location_name`, `city`, `region_code` | three cafes |
| `waste_reasons.csv` | `dim_waste_reason` | `waste_reason` | `avoidability`, `avoidability_flag`, `prevention_lever` | policy classification, maintained by ops analytics |

`raw.*` tables in the warehouse keep the delivered bytes as text. `silver.*` are
the validated, normalised, deduplicated tables the models read.

## Published marts

| Mart | Grain | Purpose |
|---|---|---|
| `mart_waste_opportunity` | `waste_date` + `location_id` + `ingredient_id` + `waste_reason` | waste with its context: cost, demand, inventory, coverage ratios |
| `mart_waste_priority` | same as the opportunity mart | the prevention backlog: opportunity score, rank, tier, per-row trust state |
| `mart_waste_daily` | `waste_date` + `location_id` | trend series with a 7 day rolling average |
| `mart_waste_by_reason` | `waste_reason` | cost, quantity, avoidability and the lever per reason |
| `mart_waste_by_ingredient` | `ingredient_id` + `location_id` | cost concentration |
| `mart_waste_by_category` | `category` | cost by ingredient category |
| `mart_demand_events` | `event_id` + `location_id` | measured demand lift, waste in window, attendance confidence |
| `mart_purchase_plan` | `location_id` + `ingredient_id` | recommended order quantity and cover days |
| `mart_food_loss_summary` | `location_id`, plus one `all` row | estate level summary; the source of every headline number |
| `mart_metric_registry` | `metric_key` | definition, source model, measurement type, allowed trust states, owner, caveat |
| `mart_dq_expectations` | `check_id` | declared expectations with their executable `check_spec` and severity |

## Published artefacts

`data/marts/` holds 22 JSON artefacts and nothing else. A file is only there
when the trust engine approved it; when the gate closes, the export removes the
measurement files and keeps the diagnostics.

| Group | Files | Read by |
|---|---|---|
| Measurements | `overview`, `waste_priority`, `waste_daily`, `waste_by_reason`, `waste_by_ingredient`, `waste_by_category`, `demand_events`, `purchase_plan`, `food_loss_summary`, `waste_opportunity` | the dashboard and any other consumer |
| Trust diagnostics | `trust_report`, `publish_status`, `dq_expectations`, `metric_registry`, `lineage`, `reconciliation`, `run_metadata` | the dashboard's trust and pipeline pages |
| Dimensions | `dim_date`, `dim_location`, `dim_ingredient`, `dim_product`, `dim_waste_reason` | consumers that need the conformed keys |

The dashboard itself fetches only the eleven artefacts it renders. The rest
stay published because they are the audit trail and the dimensions other
consumers join on.

## Published metrics

| Metric key | Type | Numerator / denominator | Caveat |
|---|---|---|---|
| `waste_cost_at_risk` | derived | avoidable waste priced at purchase-unit cost | purchase cost, not landed or net of discount |
| `avoidable_cost_share` | derived | avoidable cost / total cost | avoidability is a policy classification |
| `waste_rate_per_demand` | derived | total waste / total demand of the same ingredients | ratio of totals; the denominator covers the wasted ingredients, not the whole menu |
| `waste_quantity` | measured | recorded waste quantity | source recorded, no estimation applied |
| `units_sold` | measured | point-of-sale units | system of record |
| `demand_lift_pct` | derived | units sold in the 7 day window / 7 against the 17 day baseline | measured lift only; forward-looking events carry none |
| `expected_attendance` | estimated | organiser estimate | an estimate, never a measurement; confidence is carried per event |
| `recommended_order_qty` | estimated | `avg_daily_demand * cover_days - stock_on_hand` | planning heuristic, not an order commitment |

## Trust vocabulary

| Term | Meaning |
|---|---|
| `measured` | every expectation protecting the metric's lineage passed |
| `partial` | a warning fired, or the metric is an estimate |
| `unverified` | a blocking expectation protecting the lineage failed, or nothing protects the metric |
| `displayable` | the metric is published and its state is allowed by the registry |
| `protected` | a dbt test or a declared expectation could catch this metric breaking |
| `coverage` | the share of a row's inputs that have a denominator behind them |
| `quarantine` | rows rejected by the contract, with a reason each |

## Two rules that must not drift

- **Waste rate needs a stable denominator.** The published waste rate divides
  total waste by the total demand of the same ingredients on the same days and
  locations. It is a ratio of totals. An average of daily ratios is a different
  number (86.5% against 31.7% on the same data) and must never be published
  under the same name.
- **A future event has no measured lift.** Events after the data window carry
  an attendance signal only. A lift value for them is a forecast and this
  platform does not publish forecasts.
