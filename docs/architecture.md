# Architecture and ownership

## Selected design

Batch processing on a local DuckDB warehouse, with a trust layer between the
warehouse and every consumer. The design is chosen because it is cheap,
reproducible, and because the hard part of this problem is not the SQL: it is
deciding which numbers are allowed out of the door.

1. **Contracts first.** `ingestion/contracts.py` declares, per source, the
   expected types, nullability, ranges, enumerations, grain and natural key.
   Nothing downstream is allowed to be more forgiving than the contract.
2. **Bronze keeps the truth.** Every delivery is snapshotted to Parquet with a
   manifest (sha256, row counts, run id, timestamps). Nothing rewrites bronze.
3. **Silver cleans once.** Validate, normalise, deduplicate on the natural key,
   quarantine rejects with reasons, and publish `raw.*` and `silver.*` tables
   into the warehouse. `raw.*` is stored as all-varchar so the delivered bytes
   remain auditable.
4. **dbt owns the business meaning.** Seven staging views, two intermediates, five
   dimensions, four facts, eleven marts. Business rules live in
   `dbt_project.yml` vars, not in the dashboard.
5. **The trust engine decides what may be shown.** It evaluates the declared
   expectations in `mart_dq_expectations`, assigns a trust state to every
   published metric, and opens or closes the publication gate.
6. **The export is the only writer of dashboard artefacts.** When the gate is
   closed it removes the previously published numbers, so the dashboard cannot
   serve last run's figures under this run's status. When a single metric is not
   allowed to be shown, its published value is `null` rather than the number, so
   the dashboard cannot display a figure the trust engine refused.
7. **The dashboard is a static reader.** No framework, no build step, no KPI
   math, no warehouse access.

## Boundaries (Python vs dbt vs the browser)

| Layer | Owns |
|---|---|
| Python ingestion | structural validation, type casting, unit normalisation, deduplication, quarantine, snapshotting, I/O |
| dbt | business definitions, denominators and rates, avoidability classification, opportunity scoring, dimensional modelling, tests, freshness, lineage |
| Trust engine | expectation evaluation, trust states, publication gate, lineage export |
| Browser | selection, filtering, layout, labelling, honesty about what is estimated |

The browser never computes a published metric. The export never invents a
definition. dbt never guesses at a contract.

## Grain

| Model | Grain |
|---|---|
| `silver.sales` | `sale_id` |
| `silver.inventory_snapshots` | `location_id`, `snapshot_date`, `ingredient_id` |
| `silver.waste_events` | `waste_id` |
| `silver.events` | `event_id` |
| `fct_sales` | `sale_id` |
| `fct_waste_events` | `waste_id` |
| `fct_inventory_snapshot` | `location_id`, `snapshot_date`, `ingredient_id` |
| `fct_demand_events` | `event_id` |
| `mart_waste_opportunity` | `waste_date`, `location_id`, `ingredient_id`, `waste_reason` |
| `mart_waste_priority` | same as the opportunity mart; ranking adds columns, not grain |
| `mart_waste_daily` | `waste_date`, `location_id` |
| `mart_demand_events` | `event_id`, `location_id` |
| `mart_purchase_plan` | `location_id`, `ingredient_id` |
| `mart_food_loss_summary` | `location_id`, plus one `all` row for the estate |

Every join uses the full business key. The earlier version of
`int_waste_with_context` joined on date and location only and multiplied each
waste row by every product on that day; the grain table above and the tests in
`tests/test_warehouse.py` exist to keep that from coming back.

## Trust states

| State | Meaning |
|---|---|
| `measured` | every expectation protecting this metric's lineage passed |
| `partial` | a warning fired, or the metric is an estimate |
| `unverified` | a blocking expectation protecting the lineage failed, or nothing protects the metric |

A metric inherits the state of every check that protects any model in its
lineage, not only its own model. An estimate is never promoted to `measured`.
A metric is displayed only in a state its registry entry allows.

## Protection

A metric is only as trustworthy as the rules that could catch it breaking. The
engine therefore requires every published metric to be *protected*: its source
model, or a model upstream of it, must have a dbt test attached or be the target
of a declared expectation. `dq_metric_coverage` enforces this.

An unprotected metric is marked `unverified`, is not displayable, and the export
publishes `null` for it. The trust console shows a `checked` / `uncovered` chip
next to every metric, so the gap is visible rather than silent.

## Promises

The registry also decides which metrics the dashboard shows. That promise is
checked too: `dq_dashboard_consistency` compares the metrics marked
`display_in_dashboard` against the states the engine actually allowed. When a
metric can no longer be shown, the export withholds its value and the check
reports the mismatch, so the registry cannot quietly promise something the data
no longer supports.

## Reproducibility

A published artefact is a contract with the dashboard and with whoever reviews
the repository. A diff in `data/marts/` has to mean a real change, so the
pipeline is deterministic by construction:

- The synthetic generator is seeded, so the same source data comes out every run.
- Every published table declares the key its rows are sorted by. DuckDB does not
  promise an order for a plain select, so the order is stated rather than
  assumed.
- The ranks in the marts break ties on the full grain, and the `any_value`
  aggregations are replaced by `min`, so two runs cannot swap two rows.
- Published floats are rounded to the precision they are meaningful at. A
  floating point sum depends on the order the rows are added up in, so the same
  data can add up to 17.67 or 17.669999999999998.
- One delivery carries one ingest timestamp. A per-source timestamp drifts by
  seconds depending on where the clock crossed a second boundary, and the
  freshness check would then name a different oldest source from one run to
  the next.

CI rebuilds the whole pipeline from a clean checkout and asserts that the
artefacts come out byte-identical, apart from the run id, the timestamps and
the two fields that legitimately depend on the wall clock: the observed value
of a freshness or recency check, and the age in days inside its message. The
words around that age are compared, so a check that starts naming a different
source still fails the comparison.

## Scheduling

The pipeline is a plain Python step runner (`orchestration/pipeline.py`), so it
runs from a shell, from CI or from a scheduler. Airflow is the optional
scheduled form of it (`airflow/dags/wastewise_pipeline.py`): one DAG with the
same tasks in the same order, a daily schedule, backfill for a missed day, a
retry only for the warehouse build, and the publish step on the `all_done`
trigger rule so a refused gate still withdraws the numbers. The DAG calls the
same scripts, so there is one implementation of the pipeline and one
implementation of the gate verdict (`scripts/gate_status.py`), and the CI job
and the scheduler read the same verdict from the same artefacts.

## Failure behavior

- A contract failure stops the run before anything is published. Rejects go to
  `data/quarantine/<source>.errors.json` with a reason per row.
- Natural-key deduplication makes retries idempotent.
- A blocking expectation failure closes the publication gate: the export removes
  the previously published numbers, the data routes render the block instead of
  stale figures, and the trust console explains which expectation failed. The
  registry, expectations, trust report and lineage stay published because they
  are what explains the block.
- A metric that loses its protection is demoted to `unverified` on its own, so
  one uncovered metric does not take the whole dashboard down with it.
- A metric the registry promises to the dashboard but the engine withholds is
  reported by `dq_dashboard_consistency` and published as `null`, never as a
  number the gate did not approve.
- Source freshness is declared in `sources.yml` (warn after 12h, error after
  3d) and evaluated by the trust engine.
- Credentials come from environment variables only and are never written to a
  file.

## Ownership

| Area | Owner |
|---|---|
| Contracts, ingestion, quarantine | data engineering |
| Business definitions, marts, tests | ops analytics |
| Trust states, publication gate | data engineering with ops analytics sign-off |
| Metric registry entries | the named metric owner in the registry |
| Dashboard rendering | front end |

## Cost controls

The local runner needs no services beyond DuckDB. dbt runs with two threads.
Snowflake is optional: the profile keeps a `snowflake` target, and
`dbt build --target snowflake` is the only place it is used. No always-on
scheduler is required; the pipeline is a batch job that exits non-zero when the
publication gate is closed.
